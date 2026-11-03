import numpy as np
import pandas as pd
import pytest

from screener import SIDE_ABOVE, SIDE_BELOW, compute_metrics, screen


def bars(closes, code="1000", spread=1.0, volume=1_000_000, end="2026-10-30"):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "code": code,
            "date": pd.bdate_range(end=end, periods=len(closes)),
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volume,
        }
    )


def one(closes, **kwargs):
    return compute_metrics(bars(closes, **kwargs)).iloc[0]


# 200日線(≒1000)へ上から下落してくる: 1000が250本続いた後、1100から毎日5円下がって1040へ
FALLING = [1000.0] * 250 + list(np.arange(1100, 1035, -5.0))
RISING = [1000.0] * 250 + list(np.arange(900, 965, 5.0))


def test_ma_and_gap_match_hand_calculation():
    closes = np.arange(1, 301, dtype=float)
    m = one(closes, spread=0.5)
    assert m["ma200"] == pytest.approx(closes[-200:].mean())
    assert m["gap_pct"] == pytest.approx((300 - 200.5) / 200.5 * 100)


def test_approaching_from_above():
    m = one(FALLING)
    assert m["side"] == SIDE_ABOVE
    assert m["speed"] > 0
    assert np.isfinite(m["days_to_touch"])


def test_approaching_from_below():
    m = one(RISING)
    assert m["side"] == SIDE_BELOW
    assert m["speed"] > 0
    assert m["gap_pct"] < 0


def test_moving_away_is_not_approaching():
    m = one([1000.0] * 250 + list(np.arange(1040, 1105, 5.0)))
    assert m["speed"] < 0
    assert np.isnan(m["days_to_touch"])
    assert screen(compute_metrics(bars([1000.0] * 250 + list(np.arange(1040, 1105, 5.0)))), max_atr=99, max_pct=99).empty


def test_recent_cross_is_not_approaching():
    # 5営業日前は線の下、現在は線の上 → 跨いだ直後なので「接近」扱いにしない
    m = one([1000.0] * 295 + [950, 960, 1020, 1040, 1060, 1080])
    assert m["side"] == SIDE_ABOVE
    assert m["speed"] < 0


def test_touch_today_excluded_by_default():
    m = compute_metrics(bars([1000.0] * 300, spread=5.0))
    assert m.iloc[0]["touched_today"]
    assert m.iloc[0]["days_since_touch"] == 0
    assert screen(m, approaching_only=False).empty
    assert len(screen(m, approaching_only=False, include_touched=True)) == 1


def test_days_since_touch():
    m = one([1000.0] * 250 + [1100.0] * 10, spread=1.0)
    # 1000の最終バーで線に触れてから10本経過
    assert m["days_since_touch"] == 10


def test_short_history_is_skipped():
    assert compute_metrics(bars([1000.0] * 199)).empty


def test_gap_in_exactly_200_bars_works():
    m = one([1000.0] * 199 + [1010.0])
    assert m["ma200"] == pytest.approx(1000.05)
    assert np.isnan(m["speed"])
    assert np.isnan(m["slope_pct"])


def test_suspended_stock_is_dropped():
    active = bars(FALLING, code="1000")
    halted = bars(FALLING, code="2000", end="2026-09-01")
    codes = compute_metrics(pd.concat([active, halted]))["code"].tolist()
    assert codes == ["1000"]


def test_unadjusted_split_is_flagged_and_excluded():
    # しまむらの実例: 前日終値11040円 → 始値3710円（3分割の調整漏れ）
    m = compute_metrics(bars([11040.0] * 250 + [3700.0] * 50))
    assert m.iloc[0]["split_gap"]
    assert screen(m, max_atr=99, max_pct=99, approaching_only=False, include_touched=True).empty


def test_old_split_gap_outside_ma_window_is_ignored():
    m = compute_metrics(bars([11040.0] * 50 + [3700.0] * 300))
    assert not m.iloc[0]["split_gap"]


def test_limit_moves_are_not_flagged_as_split():
    # 値幅制限ちょうどのストップ高・安、および実例の4倍拡大（6072: 648→1048）は正常
    assert not compute_metrics(bars([1000.0] * 250 + [850.0] * 50)).iloc[0]["split_gap"]
    assert not compute_metrics(bars([648.0] * 250 + [1048.0] * 50)).iloc[0]["split_gap"]


def test_screen_filters_and_sort():
    frames = [
        bars(FALLING, code="1000", spread=10),
        bars(RISING, code="2000", spread=10),
        bars(FALLING, code="3000", spread=10, volume=100),  # 売買代金が小さい
    ]
    m = compute_metrics(pd.concat(frames))
    wide = dict(max_atr=99, max_pct=99)
    assert set(screen(m, **wide)["code"]) == {"1000", "2000"}
    assert screen(m, side=SIDE_ABOVE, **wide)["code"].tolist() == ["1000"]
    assert screen(m, side=SIDE_BELOW, **wide)["code"].tolist() == ["2000"]
    assert screen(m, max_atr=0.01, max_pct=99).empty
    assert screen(m, max_atr=99, max_pct=0.01).empty
    result = screen(m, min_turnover=0, **wide)
    assert result["gap_atr"].is_monotonic_increasing
