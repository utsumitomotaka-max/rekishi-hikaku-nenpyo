"""200日移動平均線への接近度を計算し、銘柄を絞り込む。"""
from __future__ import annotations

import numpy as np
import pandas as pd

MA_WINDOW = 200
ATR_WINDOW = 14
SPEED_WINDOW = 5
SLOPE_WINDOW = 20
TURNOVER_WINDOW = 20
STALE_DAYS = 7  # 最新日からこの日数以上取引がない銘柄（売買停止など）は除外する

SIDE_ABOVE = "上から↓"
SIDE_BELOW = "下から↑"

# 東証の呼値別の値幅制限（基準値段の下限と制限値幅）
LIMIT_FLOORS = np.array(
    [0, 100, 200, 500, 700, 1000, 1500, 2000, 3000, 5000, 7000, 10000, 15000, 20000, 30000, 50000, 70000, 100000]
)
LIMIT_WIDTHS = np.array(
    [30, 50, 80, 100, 150, 300, 400, 500, 700, 1000, 1500, 3000, 4000, 5000, 7000, 10000, 15000, 30000]
)
MAX_DOWN_LIMITS = 2.0  # 制限値幅の拡大は通常ストップ安の連続後のみ。これを超える下落は分割調整漏れとみなす
MAX_UP_LIMITS = 4.1  # 上方向は最大4倍まで拡大する実例があるため、それを超えたら併合の調整漏れとみなす


def has_split_gap(open_: np.ndarray, close: np.ndarray) -> bool:
    """値幅制限では説明できない始値のギャップ（Yahoo側の分割調整漏れ）があるか。"""
    prev = close[:-1]
    width = LIMIT_WIDTHS[np.searchsorted(LIMIT_FLOORS, prev, side="right") - 1]
    move = (open_[1:] - prev) / width
    return bool(((move < -MAX_DOWN_LIMITS) | (move > MAX_UP_LIMITS)).any())


def _metrics_for(code: str, g: pd.DataFrame) -> dict | None:
    open_ = g["open"].to_numpy(dtype=float)
    close = g["close"].to_numpy(dtype=float)
    high = g["high"].to_numpy(dtype=float)
    low = g["low"].to_numpy(dtype=float)
    volume = g["volume"].to_numpy(dtype=float)
    n = len(close)
    if n < MA_WINDOW:
        return None

    ma = pd.Series(close).rolling(MA_WINDOW).mean().to_numpy()
    gap = close - ma
    sign = 1.0 if gap[-1] >= 0 else -1.0

    prev_close = close[:-1]
    true_range = np.maximum(high[1:], prev_close) - np.minimum(low[1:], prev_close)
    atr = true_range[-ATR_WINDOW:].mean()
    if atr <= 0:
        return None

    # 200日線に向かう1日あたりの速度。期間内に線を跨いだ銘柄は負になり、接近中とみなさない
    speed = np.nan
    if n >= MA_WINDOW + SPEED_WINDOW:
        speed = sign * (gap[-1 - SPEED_WINDOW] - gap[-1]) / SPEED_WINDOW
    days_to_touch = abs(gap[-1]) / speed if speed > 0 else np.nan

    slope_pct = np.nan
    if n >= MA_WINDOW + SLOPE_WINDOW:
        slope_pct = (ma[-1] / ma[-1 - SLOPE_WINDOW] - 1) * 100

    touches = np.flatnonzero((low <= ma) & (ma <= high))
    days_since_touch = n - 1 - touches[-1] if touches.size else np.nan
    lookback = MA_WINDOW + SLOPE_WINDOW

    return {
        "code": code,
        "last_date": g["date"].iloc[-1],
        "close": close[-1],
        "ma200": ma[-1],
        "gap_pct": gap[-1] / ma[-1] * 100,
        "atr": atr,
        "gap_atr": abs(gap[-1]) / atr,
        "side": SIDE_ABOVE if sign > 0 else SIDE_BELOW,
        "speed": speed,
        "days_to_touch": days_to_touch,
        "slope_pct": slope_pct,
        "touched_today": days_since_touch == 0,
        "days_since_touch": days_since_touch,
        "turnover": (close[-TURNOVER_WINDOW:] * volume[-TURNOVER_WINDOW:]).mean(),
        "split_gap": has_split_gap(open_[-lookback:], close[-lookback:]),
    }


def compute_metrics(prices: pd.DataFrame) -> pd.DataFrame:
    """日足（code, date, open, high, low, close, volume）から銘柄ごとの指標を作る。"""
    rows = [
        m
        for code, g in prices.sort_values(["code", "date"]).groupby("code", sort=False)
        if (m := _metrics_for(code, g)) is not None
    ]
    metrics = pd.DataFrame(rows)
    if metrics.empty:
        return metrics
    cutoff = metrics["last_date"].max() - pd.Timedelta(days=STALE_DAYS)
    return metrics[metrics["last_date"] >= cutoff].reset_index(drop=True)


def screen(
    metrics: pd.DataFrame,
    max_atr: float = 2.0,
    max_pct: float = 5.0,
    side: str | None = None,
    ma_trend: str | None = None,
    min_turnover: float = 100_000_000,
    approaching_only: bool = True,
    include_touched: bool = False,
) -> pd.DataFrame:
    """条件に合う銘柄を、200日線に近い順（ATR換算）で返す。

    side は SIDE_ABOVE / SIDE_BELOW、ma_trend は "up" / "down"。None なら絞り込まない。
    """
    mask = (
        (metrics["gap_atr"] <= max_atr)
        & (metrics["gap_pct"].abs() <= max_pct)
        & (metrics["turnover"] >= min_turnover)
        & ~metrics["split_gap"]
    )
    if side is not None:
        mask &= metrics["side"] == side
    if ma_trend == "up":
        mask &= metrics["slope_pct"] > 0
    elif ma_trend == "down":
        mask &= metrics["slope_pct"] < 0
    if approaching_only:
        mask &= metrics["speed"] > 0
    if not include_touched:
        mask &= ~metrics["touched_today"]
    return metrics[mask].sort_values("gap_atr").reset_index(drop=True)
