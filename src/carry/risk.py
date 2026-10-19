"""Liquidation risk of the short perp leg in a cash-and-carry position.

The trade is delta-neutral, but the two legs sit in different places: the
spot gains on a rally while the short perp loses, and the perp margin account
can be liquidated before you move the spot profit across. The question:

    For leverage L on the perp leg, how often would a holding period of H days
    (without topping up margin) have hit the liquidation price?

Short-perp liquidation (isolated margin, maintenance rate m), price rise x:
    equity = N/L - N*x  <  m * N * (1 + x)   =>   x > (1/L - m) / (1 + m)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def liquidation_move(leverage: float, maintenance: float = 0.005) -> float:
    return (1 / leverage - maintenance) / (1 + maintenance)


def max_forward_rise(spot: pd.Series, horizon_hours: int) -> pd.Series:
    """For each start hour, the largest rise above the start price within the next `horizon_hours`."""
    s = spot.to_numpy(float)
    fwd_max = pd.Series(s[::-1]).rolling(horizon_hours, min_periods=1).max().to_numpy()[::-1]
    # rolling on the reversed series covers [t, t+h-1]; shift by one to look strictly ahead
    fwd_max = np.append(fwd_max[1:], np.nan)
    out = pd.Series(fwd_max / s - 1, index=spot.index)
    out.iloc[-horizon_hours:] = np.nan
    return out


def liquidation_table(spot: pd.Series, leverages=(1, 2, 3, 5, 10, 20), horizons_days=(1, 7, 30),
                      maintenance: float = 0.005) -> pd.DataFrame:
    rows = []
    for lev in leverages:
        x = liquidation_move(lev, maintenance)
        row = {"leverage": lev, "liquidation_rise_pct": round(100 * x, 1)}
        for d in horizons_days:
            rise = max_forward_rise(spot, d * 24).dropna()
            row[f"hit_within_{d}d_pct"] = round(100 * float((rise > x).mean()), 2) if len(rise) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
