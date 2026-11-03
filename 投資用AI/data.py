"""東証の銘柄一覧と日足データの取得・保存。"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
import yfinance as yf

JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PERIOD = "2y"
CHUNK_SIZE = 100
MIN_SUCCESS_RATE = 0.8  # これを下回ったら既存データを上書きしない（レート制限などを想定）

DATA_DIR = Path(__file__).parent / "data"
UNIVERSE_PATH = DATA_DIR / "universe.parquet"
PRICES_PATH = DATA_DIR / "prices.parquet"
META_PATH = DATA_DIR / "meta.json"

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message="The inplace keyword")


def fetch_universe() -> pd.DataFrame:
    """JPX公式の一覧からプライム・スタンダード・グロースの銘柄を取得する。"""
    page = requests.get(JPX_PAGE, headers=HEADERS, timeout=60)
    page.raise_for_status()
    # ファイル名や拡張子が変わることがあるため、ページ内のリンクをたどる
    link = re.search(r'href="([^"]*data_j\.xlsx?)"', page.text)
    if link is None:
        raise RuntimeError("JPXのページに銘柄一覧へのリンクが見つかりません")
    file = requests.get(urljoin(JPX_PAGE, link.group(1)), headers=HEADERS, timeout=60)
    file.raise_for_status()

    raw = pd.read_excel(io.BytesIO(file.content), dtype=str)
    market = raw["市場・商品区分"].str.extract(r"^(プライム|スタンダード|グロース)（")[0]
    universe = pd.DataFrame(
        {
            "code": raw["コード"],
            "name": raw["銘柄名"],
            "market": market,
            "sector": raw["33業種区分"],
        }
    )
    return universe.dropna(subset=["market"]).reset_index(drop=True)


def _download_chunk(codes: list[str]) -> pd.DataFrame:
    tickers = [f"{c}.T" for c in codes]
    # auto_adjust=False: Close は分割のみ調整。証券会社のチャートと同じ200日線になる
    data = yf.download(
        tickers,
        period=PERIOD,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    frames = []
    for code, ticker in zip(codes, tickers):
        if data.empty or ticker not in data.columns.get_level_values(0):
            continue
        g = data[ticker][["Open", "High", "Low", "Close", "Volume"]].dropna(
            subset=["High", "Low", "Close"]
        )
        # 出来高0の行は上場前のダミー値や売買停止中の値で、200日線を歪めるため除く
        g = g[g["Volume"] > 0]
        if g.empty:
            continue
        g = g.rename(columns=str.lower).rename_axis("date").reset_index()
        g.insert(0, "code", code)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_prices(
    codes: list[str], on_progress: Callable[[float], None] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄の日足を取得する。戻り値は（日足、取得できなかったコード）。"""
    frames = []
    chunks = [codes[i : i + CHUNK_SIZE] for i in range(0, len(codes), CHUNK_SIZE)]
    for i, chunk in enumerate(chunks, 1):
        frames.append(_download_chunk(chunk))
        if on_progress:
            on_progress(i / len(chunks))
        time.sleep(0.5)

    prices = pd.concat(frames, ignore_index=True)
    missing = sorted(set(codes) - set(prices["code"]))
    if missing:  # 一時的な失敗を拾うため1回だけ再試行する
        retried = _download_chunk(missing)
        if not retried.empty:
            prices = pd.concat([prices, retried], ignore_index=True)
        missing = sorted(set(codes) - set(prices["code"]))
    return prices, missing


def refresh(on_progress: Callable[[float], None] | None = None) -> dict:
    """銘柄一覧と日足を取得し直して保存する。失敗時は既存データを残す。"""
    universe = fetch_universe()
    codes = universe["code"].tolist()
    prices, missing = fetch_prices(codes, on_progress)
    success = 1 - len(missing) / len(codes)
    if success < MIN_SUCCESS_RATE:
        raise RuntimeError(
            f"株価を取得できたのが{success:.0%}のみでした。"
            "時間をおいて再度お試しください（既存のデータは残しています）"
        )

    meta = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "universe_count": len(codes),
        "missing": missing,
    }
    DATA_DIR.mkdir(exist_ok=True)
    for frame, path in ((universe, UNIVERSE_PATH), (prices, PRICES_PATH)):
        tmp = path.with_suffix(".tmp")
        frame.to_parquet(tmp, index=False)
        tmp.replace(path)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def load_cache() -> tuple[pd.DataFrame, pd.DataFrame, dict] | None:
    if not (UNIVERSE_PATH.exists() and PRICES_PATH.exists() and META_PATH.exists()):
        return None
    return (
        pd.read_parquet(UNIVERSE_PATH),
        pd.read_parquet(PRICES_PATH),
        json.loads(META_PATH.read_text(encoding="utf-8")),
    )


if __name__ == "__main__":
    result = refresh(lambda p: print(f"\r{p:.0%}", end="", flush=True))
    print(f"\n完了: {result['universe_count']}銘柄 / 取得失敗 {len(result['missing'])}銘柄")
