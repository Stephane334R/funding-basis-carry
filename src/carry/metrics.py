"""Descriptive funding statistics and regimes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import venues_in

HOURS_PER_YEAR = 24 * 365


def trailing_apr(payments: pd.Series, window_hours: int) -> pd.Series:
    """Annualized funding from the payments of the last `window_hours`, known at t."""
    return payments.rolling(window_hours, min_periods=window_hours).sum() * HOURS_PER_YEAR / window_hours


def venue_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v in venues_in(panel):
        s = panel[f"f_{v}"].dropna()
        paid = s[s != 0]
        hours = len(s)
        rows.append({
            "venue": v,
            "start": s.index.min().date(),
            "end": s.index.max().date(),
            "settlements": len(paid),
            "settlement_interval_h": round(hours / max(len(paid), 1), 1),
            "apr_mean_pct": round(100 * s.sum() * HOURS_PER_YEAR / hours, 2),
            "pct_settlements_negative": round(100 * float((paid < 0).mean()), 1),
            "worst_30d_apr_pct": round(100 * trailing_apr(s, 720).min(), 2),
            "best_30d_apr_pct": round(100 * trailing_apr(s, 720).max(), 2),
        })
    return pd.DataFrame(rows)


def apr_by_year(panel: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for v in venues_in(panel):
        s = panel[f"f_{v}"]
        g = s.groupby(s.index.year)
        out[v] = (g.sum() * HOURS_PER_YEAR / g.count() * 100).round(2)
    return pd.DataFrame(out)


def rolling_apr(panel: pd.DataFrame, window_hours: int = 720) -> pd.DataFrame:
    return pd.DataFrame({v: trailing_apr(panel[f"f_{v}"], window_hours) for v in venues_in(panel)})


def regimes(panel: pd.DataFrame, window_hours: int = 720) -> pd.DataFrame:
    """Bucket time by cross-venue average 30d funding and describe each bucket.

    Answers: is high funding a bull-market phenomenon, and is the carry
    larger or riskier in those periods?
    """
    apr = rolling_apr(panel, window_hours).mean(axis=1)
    ret_30d = panel["spot"].pct_change(window_hours)
    fwd_carry = rolling_apr(panel, window_hours).mean(axis=1).shift(-window_hours)
    df = pd.DataFrame({"apr": apr, "spot_ret_30d": ret_30d, "next_30d_apr": fwd_carry,
                       "premium": panel["premium"]}).dropna(subset=["apr"])
    labels = ["negative", "low (0-5%)", "normal (5-15%)", "high (15-30%)", "extreme (>30%)"]
    df["regime"] = pd.cut(df["apr"], [-np.inf, 0, 0.05, 0.15, 0.30, np.inf], labels=labels)
    t = df.groupby("regime", observed=False).agg(
        share_of_time_pct=("apr", lambda x: 100 * len(x) / len(df)),
        avg_apr_pct=("apr", lambda x: 100 * x.mean()),
        avg_spot_ret_30d_pct=("spot_ret_30d", lambda x: 100 * x.mean()),
        avg_next_30d_apr_pct=("next_30d_apr", lambda x: 100 * x.mean()),
        avg_premium_bps=("premium", lambda x: 1e4 * x.mean()),
    )
    return t.round(2)


def funding_vs_returns_corr(panel: pd.DataFrame, window_hours: int = 720) -> float:
    apr = rolling_apr(panel, window_hours).mean(axis=1)
    ret = panel["spot"].pct_change(window_hours)
    both = pd.concat([apr, ret], axis=1).dropna()
    # non-overlapping samples to avoid inflating significance
    both = both.iloc[::window_hours]
    return float(both.corr().iloc[0, 1]) if len(both) > 3 else float("nan")
