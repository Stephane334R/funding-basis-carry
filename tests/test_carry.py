import numpy as np
import pandas as pd
import pytest

from carry import backtest, data, metrics, risk, venues
from carry.metrics import HOURS_PER_YEAR


def _panel(hours=24 * 20, rate_8h=0.0001, premium=0.0, venues_=("binance",)):
    idx = pd.date_range("2025-01-01", periods=hours, freq="1h", tz="UTC")
    p = pd.DataFrame({"spot": 100.0, "perp": 100.0 * (1 + premium)}, index=idx)
    p["premium"] = p["perp"] / p["spot"] - 1
    for v in venues_:
        p[f"f_{v}"] = np.where(np.arange(hours) % 8 == 0, rate_8h, 0.0)
    return p


def test_trailing_apr_of_constant_8h_funding():
    p = _panel(rate_8h=0.0001)
    apr = metrics.trailing_apr(p["f_binance"], 72).dropna()
    assert apr.iloc[-1] == pytest.approx(0.0001 * 3 * 365)


def test_always_on_carry_collects_funding_minus_entry_cost():
    p = _panel(rate_8h=0.0001)
    prm = backtest.CarryParams(always_on=True, lookback_hours=24, notional=1_000_000, slippage_bps=0)
    bt = backtest.cash_and_carry(p, "binance", prm)
    entry = bt["position"].ne(0).idxmax()
    paid_after_entry = p.loc[p.index > entry, "f_binance"].sum()
    assert bt["funding"].sum() == pytest.approx(paid_after_entry * 1_000_000)
    assert bt["costs"].sum() == pytest.approx(-1_000_000 * (prm.fee_spot + prm.fee_perp))
    assert bt["basis"].sum() == pytest.approx(0.0)


def test_no_lookahead_position_uses_only_past_funding():
    p = _panel(rate_8h=0.0)
    p.loc[p.index[-50]:, "f_binance"] = np.where(np.arange(50) % 8 == 0, 0.01, 0.0)  # funding spikes late
    prm = backtest.CarryParams(lookback_hours=24, entry_apr=0.10)
    bt = backtest.cash_and_carry(p, "binance", prm)
    assert bt.loc[: p.index[-51], "position"].sum() == 0  # nothing before the spike is known


def test_basis_pnl_sign_short_perp_gains_when_premium_falls():
    p = _panel(rate_8h=0.0)
    p["premium"] = np.linspace(0.002, 0.0, len(p))
    bt = backtest.cash_and_carry(p, "binance", backtest.CarryParams(always_on=True, lookback_hours=8))
    assert bt["basis"].sum() > 0


def test_cross_venue_picks_high_minus_low():
    p = _panel(rate_8h=0.0001, venues_=("binance", "bybit"))
    p["f_bybit"] *= 5  # bybit pays 5x more: short bybit, long binance
    prm = backtest.CarryParams(lookback_hours=24, entry_apr=0.10, slippage_bps=0)
    bt = backtest.cross_venue(p, prm, ["binance", "bybit"])
    live = bt[bt["short"].notna()]
    assert set(live["short"]) == {"bybit"} and set(live["long"]) == {"binance"}
    assert bt["funding"].sum() > 0
    assert bt["costs"].sum() == pytest.approx(-2 * prm.notional * prm.fee_perp)  # two legs opened once


def test_liquidation_threshold_and_forward_rise():
    assert risk.liquidation_move(1, 0) == pytest.approx(1.0)
    assert risk.liquidation_move(10, 0.005) == pytest.approx((0.1 - 0.005) / 1.005)
    s = pd.Series([100, 110, 90, 130, 100.0])
    rise = risk.max_forward_rise(s, 2)
    assert rise.iloc[0] == pytest.approx(0.10)   # next 2 hours: 110, 90
    assert rise.iloc[2] == pytest.approx(130 / 90 - 1)


def test_hourly_panel_alignment_and_missing_venue_history():
    t = pd.date_range("2025-01-01", periods=48, freq="1h", tz="UTC")
    spot = pd.DataFrame({"ts": t, "close": 100.0})
    perp = pd.DataFrame({"ts": t, "close": 100.1})
    funding = pd.DataFrame({
        "ts": [t[8] + pd.Timedelta(milliseconds=3), t[16], t[30]],
        "venue": ["binance", "binance", "okx"], "coin": "BTC", "rate": [0.0001, 0.0002, 0.0003]})
    panel = data.hourly_panel(funding, spot, perp)
    assert panel.loc[t[8], "f_binance"] == 0.0001  # settlement floored to its hour
    assert panel["premium"].iloc[0] == pytest.approx(0.001)
    assert np.isnan(panel.loc[t[10], "f_okx"])      # before okx's first record: unknown, not zero


class _Resp:
    def __init__(self, payload):
        self.payload, self.status_code = payload, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_venue_parsers_with_mocked_responses(monkeypatch):
    start, end = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-02", tz="UTC")
    t0 = int(start.timestamp() * 1000)
    payloads = {
        "fapi.binance.com/fapi/v1/fundingRate": [[{"symbol": "BTCUSDT", "fundingTime": t0 + 8 * 3_600_000, "fundingRate": "0.0001", "markPrice": "1"}]],
        "api.bybit.com": [{"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": str(t0 + 16 * 3_600_000)}]}},
                          {"retCode": 0, "result": {"list": []}}],
        "www.okx.com": [{"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "fundingRate": "0.0003", "realizedRate": "0.00031", "fundingTime": str(t0)}]}],
        "api.hyperliquid.xyz": [[{"coin": "BTC", "fundingRate": "0.0000125", "premium": "0", "time": t0 + 3_600_000}], []],
    }
    calls = {k: 0 for k in payloads}

    def fake_request(method, url, params=None, json=None, timeout=None):
        for key, seq in payloads.items():
            if key in url:
                i = min(calls[key], len(seq) - 1)
                calls[key] += 1
                return _Resp(seq[i])
        raise AssertionError(url)

    monkeypatch.setattr(venues._session, "request", fake_request)
    monkeypatch.setattr(venues.time, "sleep", lambda s: None)

    assert venues.binance_funding("BTC", start, end)["rate"].tolist() == [0.0001]
    assert venues.bybit_funding("BTC", start, end)["rate"].tolist() == [0.0002]
    assert venues.okx_funding("BTC", start, end)["rate"].tolist() == [0.00031]
    hl = venues.hyperliquid_funding("BTC", start, end)
    assert hl["rate"].tolist() == [0.0000125] and hl["venue"].iloc[0] == "hyperliquid"
