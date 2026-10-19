"""Storage and the hourly panel every analysis runs on.

Timing convention on the hourly grid (index = instant t, UTC, on the hour):

* `spot`, `perp`   : prices at instant t (close of the 1h bar ending at t)
* `premium`        : perp / spot - 1 at instant t
* `f_<venue>`      : funding paid AT instant t (sum of settlements in [t, t+1h),
                     floored to t). Positive = longs pay shorts.

A position decided at t (using only data up to t) is held over (t, t+1] and
receives the funding paid at t+1 plus the premium change from t to t+1.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import venues


def fetch_all(coins: list[str], venue_names: list[str], start: pd.Timestamp, end: pd.Timestamp, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for coin in coins:
        for v in venue_names:
            df = venues.FUNDING_FETCHERS[v](coin, start, end)
            df.to_parquet(root / f"funding_{v}_{coin}.parquet", index=False)
            print(f"{v:<12} {coin:<5} {len(df):>6} settlements  {df['ts'].min()} -> {df['ts'].max()}")
        venues.binance_spot_hourly(coin, start, end).to_parquet(root / f"spot_{coin}.parquet", index=False)
        venues.binance_perp_hourly(coin, start, end).to_parquet(root / f"perp_{coin}.parquet", index=False)


def load_raw(root: Path, coin: str, venue_names: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    funding = pd.concat(
        [pd.read_parquet(root / f"funding_{v}_{coin}.parquet") for v in venue_names
         if (root / f"funding_{v}_{coin}.parquet").exists()],
        ignore_index=True,
    )
    return funding, pd.read_parquet(root / f"spot_{coin}.parquet"), pd.read_parquet(root / f"perp_{coin}.parquet")


def hourly_panel(funding: pd.DataFrame, spot: pd.DataFrame, perp: pd.DataFrame) -> pd.DataFrame:
    """Build the hourly panel. `spot`/`perp` carry the bar OPEN time, so we shift by 1h
    to label each close at the instant it is observed."""
    px = pd.DataFrame({
        "spot": spot.set_index(spot["ts"] + pd.Timedelta(hours=1))["close"],
        "perp": perp.set_index(perp["ts"] + pd.Timedelta(hours=1))["close"],
    })
    idx = pd.date_range(px.index.min(), px.index.max(), freq="1h")
    panel = px.reindex(idx).ffill()
    panel["premium"] = panel["perp"] / panel["spot"] - 1

    f = funding.assign(hour=funding["ts"].dt.floor("1h"))
    wide = f.pivot_table(index="hour", columns="venue", values="rate", aggfunc="sum")
    for v in wide.columns:
        panel[f"f_{v}"] = wide[v].reindex(idx).fillna(0.0)
        # mark hours before the venue's first / after its last record as missing, not zero
        first, last = wide[v].first_valid_index(), wide[v].last_valid_index()
        panel.loc[(panel.index < first) | (panel.index > last), f"f_{v}"] = float("nan")
    panel.index.name = "ts"
    return panel


def venues_in(panel: pd.DataFrame) -> list[str]:
    return [c[2:] for c in panel.columns if c.startswith("f_")]
