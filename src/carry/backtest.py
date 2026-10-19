"""Carry strategy backtests on the hourly panel (see data.py for timing).

1. Cash-and-carry on one venue: long spot, short perp, same notional.
   Hourly PnL = funding received + basis PnL - trading costs
     funding  = pos_{t-1} * N * f_t                    (short perp receives positive funding)
     basis    = -pos_{t-1} * N * (premium_t - premium_{t-1})
   Capital    = N (spot) + N / leverage (perp margin)

2. Cross-venue funding arbitrage: short the perp on the venue with the highest
   trailing funding, long the perp on the lowest.
   Hourly PnL = N * (f_short,t - f_long,t) - costs
   Capital    = 2 * N / leverage

Entry/exit use trailing funding only (no look-ahead) with hysteresis
(enter above `entry_apr`, exit below `exit_apr`).

Simplifications to state in the write-up:
* Basis PnL uses the Binance perp premium for every venue (we only have one
  perp price series). Venue-specific perp prices would change the numbers
  around entries and exits, not the funding income.
* Cross-venue legs are assumed to have zero price divergence (perp vs perp
  basis across venues is small but not zero, especially in stress).
* No margin interest, no withdrawal / transfer costs, no exchange default risk.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import venues_in
from .metrics import HOURS_PER_YEAR, trailing_apr


@dataclass
class CarryParams:
    lookback_hours: int = 72
    entry_apr: float = 0.10
    exit_apr: float = 0.03
    fee_spot: float = 0.0010      # taker, fraction of notional per trade
    fee_perp: float = 0.0005
    slippage_bps: float = 1.0     # per leg per trade
    leverage: float = 3.0
    notional: float = 1_000_000.0
    always_on: bool = False       # passive baseline: hold the position all the time


def _hysteresis(signal: pd.Series, entry: float, exit_: float) -> pd.Series:
    pos, state = np.zeros(len(signal)), 0
    for i, x in enumerate(signal.to_numpy()):
        if np.isnan(x):
            state = 0
        elif state == 0 and x > entry:
            state = 1
        elif state == 1 and x < exit_:
            state = 0
        pos[i] = state
    return pd.Series(pos, index=signal.index)


def cash_and_carry(panel: pd.DataFrame, venue: str, p: CarryParams = CarryParams()) -> pd.DataFrame:
    f = panel[f"f_{venue}"]
    signal = trailing_apr(f, p.lookback_hours)
    pos = pd.Series(np.where(signal.notna(), 1.0, 0.0), index=panel.index) if p.always_on \
        else _hysteresis(signal, p.entry_apr, p.exit_apr)

    held = pos.shift(1).fillna(0.0)
    out = pd.DataFrame(index=panel.index)
    out["position"] = pos
    out["funding"] = held * p.notional * f.fillna(0.0)
    out["basis"] = -held * p.notional * panel["premium"].diff().fillna(0.0)
    trades = pos.diff().abs().fillna(pos.iloc[0])
    out["costs"] = -trades * p.notional * (p.fee_spot + p.fee_perp + 2 * p.slippage_bps / 1e4)
    out["pnl"] = out[["funding", "basis", "costs"]].sum(axis=1)
    out["capital"] = p.notional * (1 + 1 / p.leverage)
    return out


def cross_venue(panel: pd.DataFrame, p: CarryParams = CarryParams(), venue_list: list[str] | None = None,
                switch_margin_apr: float = 0.05) -> pd.DataFrame:
    vs = venue_list or venues_in(panel)
    sig = pd.DataFrame({v: trailing_apr(panel[f"f_{v}"], p.lookback_hours) for v in vs})
    fund = pd.DataFrame({v: panel[f"f_{v}"].fillna(0.0) for v in vs})

    short_leg, long_leg = [None] * len(panel), [None] * len(panel)
    cur = None
    for i, (_, row) in enumerate(sig.iterrows()):
        row = row.dropna()
        if len(row) < 2:
            cur = None
        else:
            hi, lo = row.idxmax(), row.idxmin()
            best = row[hi] - row[lo]
            if cur is None:
                if best > p.entry_apr:
                    cur = (hi, lo)
            else:
                held_spread = row.get(cur[0], np.nan) - row.get(cur[1], np.nan)
                if np.isnan(held_spread) or held_spread < p.exit_apr:
                    cur = (hi, lo) if best > p.entry_apr else None
                elif best > held_spread + switch_margin_apr and (hi, lo) != cur:
                    cur = (hi, lo)
        short_leg[i], long_leg[i] = (cur if cur else (None, None))

    out = pd.DataFrame({"short": short_leg, "long": long_leg}, index=panel.index)
    col = {v: j for j, v in enumerate(vs)}
    F = fund.to_numpy()
    rows = np.arange(len(panel))

    def paid(legs: pd.Series) -> np.ndarray:
        j = np.array([col.get(v, -1) for v in legs.fillna("")])
        return np.where(j >= 0, F[rows, np.maximum(j, 0)], 0.0)

    held_s = out["short"].shift(1).fillna("")
    held_l = out["long"].shift(1).fillna("")
    out["funding"] = p.notional * (paid(held_s) - paid(held_l))
    out["basis"] = 0.0

    # each leg change = close the old perp position (if any) + open the new one (if any)
    trades = 0
    for now, before in ((out["short"].fillna(""), held_s), (out["long"].fillna(""), held_l)):
        changed = now != before
        trades = trades + (changed & (before != "")).astype(int) + (changed & (now != "")).astype(int)
    out["costs"] = -trades * p.notional * (p.fee_perp + p.slippage_bps / 1e4)
    out["pnl"] = out[["funding", "basis", "costs"]].sum(axis=1)
    out["position"] = out["short"].notna().astype(float)
    out["capital"] = 2 * p.notional / p.leverage
    return out


def stats(bt: pd.DataFrame) -> dict:
    cap = float(bt["capital"].iloc[0])
    r = bt["pnl"] / cap
    years = len(bt) / HOURS_PER_YEAR
    equity = bt["pnl"].cumsum()
    dd = (equity - equity.cummax()).min() / cap
    daily = r.groupby(bt.index.floor("1D")).sum()
    sharpe = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else float("nan")
    return {
        "years": round(years, 2),
        "return_on_capital_apr_pct": round(100 * r.sum() / years, 2) if years else None,
        "sharpe_daily_annualized": round(float(sharpe), 2),
        "max_drawdown_pct_capital": round(100 * float(dd), 2),
        "time_invested_pct": round(100 * float(bt["position"].mean()), 1),
        "round_trips": int((bt["position"].diff() > 0).sum()),
        "pnl_funding": round(float(bt["funding"].sum()), 0),
        "pnl_basis": round(float(bt["basis"].sum()), 0),
        "pnl_costs": round(float(bt["costs"].sum()), 0),
        "pnl_total": round(float(bt["pnl"].sum()), 0),
    }
