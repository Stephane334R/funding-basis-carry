"""Synthetic hourly panel so the analysis runs offline.

Contains the stylised facts of crypto funding: persistent positive funding
in bull phases, short negative episodes after crashes, venue-specific noise
around a common factor, 8h settlements on CEXs and hourly on Hyperliquid,
and a perp premium that co-moves with funding. Use it to test the code, not
to draw conclusions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import HOURS_PER_YEAR


def generate_panel(days: int = 730, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 24
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")

    # common funding factor (annualized), AR(1) around a regime-dependent mean
    regime_mean = np.repeat(rng.choice([0.02, 0.08, 0.20, 0.35], size=days // 30 + 1, p=[0.25, 0.35, 0.3, 0.1]), 30 * 24)[:n]
    apr = np.empty(n)
    apr[0] = 0.08
    for t in range(1, n):
        apr[t] = apr[t - 1] + 0.01 * (regime_mean[t] - apr[t - 1]) + 0.012 * rng.standard_normal()

    # price: drift linked to funding regime, plus occasional crashes that flip funding negative
    ret = 0.6 * regime_mean / HOURS_PER_YEAR + rng.standard_normal(n) * 0.55 / np.sqrt(HOURS_PER_YEAR)
    crashes = rng.random(n) < 1 / (24 * 90)
    ret[crashes] -= rng.uniform(0.08, 0.15, crashes.sum())
    for t in np.flatnonzero(crashes):
        apr[t:t + 72] -= np.linspace(0.6, 0.0, len(apr[t:t + 72]))
    spot = 60_000 * np.exp(np.cumsum(ret))
    premium = apr / 365 * 3 + rng.standard_normal(n) * 2e-4   # ~ a few bps, tracks funding

    panel = pd.DataFrame({"spot": spot, "perp": spot * (1 + premium)}, index=idx)
    panel["premium"] = panel["perp"] / panel["spot"] - 1

    venue_noise = {"binance": 0.03, "bybit": 0.05, "okx": 0.05, "hyperliquid": 0.10}
    venue_bias = {"binance": 0.0, "bybit": 0.01, "okx": -0.005, "hyperliquid": 0.03}
    hours = np.arange(n)
    for v, sd in venue_noise.items():
        noise = np.zeros(n)
        for t in range(1, n):
            noise[t] = 0.995 * noise[t - 1] + sd * 0.1 * rng.standard_normal()
        venue_apr = apr + venue_bias[v] + noise
        if v == "hyperliquid":
            pay = venue_apr / HOURS_PER_YEAR
        else:
            settle = hours % 8 == 0
            pay = np.where(settle, venue_apr * 8 / HOURS_PER_YEAR, 0.0)
        panel[f"f_{v}"] = pay
    panel.index.name = "ts"
    return panel
