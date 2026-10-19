"""Static report figures (PNG)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# reference palette: categorical slots in fixed order, assigned per entity (never by rank)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
VENUE_COLORS = {"binance": SERIES[0], "bybit": SERIES[1], "okx": SERIES[2], "hyperliquid": SERIES[3]}
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


def _style(ax, title: str, ylabel: str = "") -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)


def rolling_funding(apr: pd.DataFrame, path: Path, window_label: str = "30d") -> None:
    fig, ax = plt.subplots(figsize=(9, 4), facecolor=SURFACE)
    for v in apr.columns:
        c = VENUE_COLORS.get(v, SERIES[4])
        y = 100 * apr[v]
        ax.plot(apr.index, y, lw=1.4, color=c, label=v)
    ax.axhline(0, color=AXIS, lw=0.8)
    _style(ax, f"Trailing {window_label} funding, annualized", "% APR (received by shorts)")
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left")
    ax.set_xlim(apr.dropna(how="all").index[0], apr.index[-1])
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def equity_curves(curves: dict[str, pd.Series], path: Path) -> None:
    """curves: name -> cumulative return on capital (fraction)."""
    fig, ax = plt.subplots(figsize=(9, 4), facecolor=SURFACE)
    for i, (name, s) in enumerate(curves.items()):
        y = 100 * s
        ax.plot(s.index, y, lw=2 if i == 0 else 1.4, color=SERIES[i % len(SERIES)], label=name)
        ax.annotate(name, (s.index[-1], y.iloc[-1]), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=INK2)
    ax.axhline(0, color=AXIS, lw=0.8)
    _style(ax, "Carry strategies: cumulative return on capital, after costs", "%")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    first = min(s.index[0] for s in curves.values())
    last = max(s.index[-1] for s in curves.values())
    ax.set_xlim(first, last + (last - first) * 0.22)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def liquidation_bars(table: pd.DataFrame, path: Path) -> None:
    cols = [c for c in table.columns if c.startswith("hit_within_")]
    fig, ax = plt.subplots(figsize=(8, 3.8), facecolor=SURFACE)
    width = 0.8 / len(cols)
    x = range(len(table))
    for i, c in enumerate(cols):
        label = c.replace("hit_within_", "").replace("_pct", "") + " holding"
        ax.bar([xi + i * width for xi in x], table[c], width=width * 0.92, color=SERIES[i], label=label)
    ax.set_xticks([xi + width * (len(cols) - 1) / 2 for xi in x], [f"{l:g}x" for l in table["leverage"]])
    _style(ax, "Short perp leg: share of entry times that hit liquidation", "% of start hours")
    ax.set_xlabel("leverage on the perp leg (no margin top-up)", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
