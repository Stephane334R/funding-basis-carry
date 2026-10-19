"""Command line.

    # offline demo
    python -m carry.cli report --synthetic --out reports/demo

    # real data
    python -m carry.cli fetch --coins BTC ETH --start 2024-01-01
    python -m carry.cli report --coin BTC --out reports/BTC
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from . import backtest, metrics, plots, risk
from .data import fetch_all, hourly_panel, load_raw, venues_in
from .synthetic import generate_panel

ALL_VENUES = ["binance", "bybit", "okx", "hyperliquid"]


def report(panel: pd.DataFrame, out: Path, params: backtest.CarryParams, carry_venue: str = "binance") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    vs = venues_in(panel)

    venue_tbl = metrics.venue_table(panel)
    by_year = metrics.apr_by_year(panel)
    regimes = metrics.regimes(panel)
    liq = risk.liquidation_table(panel["spot"])
    venue_tbl.to_csv(out / "venues.csv", index=False)
    by_year.to_csv(out / "apr_by_year.csv")
    regimes.to_csv(out / "regimes.csv")
    liq.to_csv(out / "liquidation.csv", index=False)

    results, curves = {}, {}
    # fixed ex ante (deepest spot + perp liquidity), NOT the venue with the best
    # funding over the sample, which would be look-ahead bias
    best_venue = carry_venue
    for name, bt in {
        f"carry {best_venue}, always on": backtest.cash_and_carry(panel, best_venue, replace(params, always_on=True)),
        f"carry {best_venue}, threshold": backtest.cash_and_carry(panel, best_venue, params),
        "cross-venue funding arb": backtest.cross_venue(panel, params, vs),
    }.items():
        results[name] = backtest.stats(bt)
        curves[name] = (bt["pnl"] / bt["capital"]).cumsum()
        bt.to_csv(out / f"bt_{name.replace(' ', '_').replace(',', '')}.csv")

    plots.rolling_funding(metrics.rolling_apr(panel), out / "rolling_funding.png")
    plots.equity_curves(curves, out / "equity_curves.png")
    plots.liquidation_bars(liq, out / "liquidation.png")

    summary = {
        "period": [str(panel.index.min()), str(panel.index.max())],
        "params": asdict(params),
        "venues": venue_tbl.to_dict(orient="records"),
        "funding_vs_30d_return_corr": round(metrics.funding_vs_returns_corr(panel), 3),
        "strategies": results,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download funding + prices into data/raw")
    f.add_argument("--coins", nargs="+", default=["BTC", "ETH"])
    f.add_argument("--venues", nargs="+", default=ALL_VENUES)
    f.add_argument("--start", default=None, help="YYYY-MM-DD")
    f.add_argument("--days", type=int, default=730, help="used when --start is not given")
    f.add_argument("--raw", type=Path, default=Path("data/raw"))

    r = sub.add_parser("report", help="run the analysis and write tables + figures")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--coin")
    r.add_argument("--venues", nargs="+", default=ALL_VENUES)
    r.add_argument("--raw", type=Path, default=Path("data/raw"))
    r.add_argument("--out", type=Path, default=Path("reports/latest"))
    r.add_argument("--entry-apr", type=float, default=0.10)
    r.add_argument("--exit-apr", type=float, default=0.03)
    r.add_argument("--lookback-hours", type=int, default=72)
    r.add_argument("--leverage", type=float, default=3.0)
    r.add_argument("--carry-venue", default="binance", help="venue for the single-venue cash-and-carry")

    a = p.parse_args()
    if a.cmd == "fetch":
        end = pd.Timestamp.now(tz="UTC").floor("1h")
        start = pd.Timestamp(a.start, tz="UTC") if a.start else end - pd.Timedelta(days=a.days)
        fetch_all(a.coins, a.venues, start, end, a.raw)
        return

    panel = generate_panel() if a.synthetic else hourly_panel(*load_raw(a.raw, a.coin, a.venues))
    params = backtest.CarryParams(entry_apr=a.entry_apr, exit_apr=a.exit_apr,
                                  lookback_hours=a.lookback_hours, leverage=a.leverage)
    summary = report(panel, a.out, params, a.carry_venue)
    print(json.dumps(summary["strategies"], indent=2))


if __name__ == "__main__":
    main()
