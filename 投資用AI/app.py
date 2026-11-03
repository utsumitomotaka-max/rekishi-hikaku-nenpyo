"""200日線タッチ候補スクリーナー（東証上場銘柄）。"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import data
from screener import MA_WINDOW, SIDE_ABOVE, SIDE_BELOW, compute_metrics, screen

CHART_DAYS = 250
COLOR_MA200 = "#2a78d6"
COLOR_MA75 = "#eda100"
COLOR_MA25 = "#52514e"
COLOR_UP = "#e34948"
COLOR_DOWN = "#1baf7a"
COLOR_VOLUME = "#c3c2b7"
COLOR_GRID = "#e1e0d9"
COLOR_MUTED = "#52514e"

SIDE_OPTIONS = {"両方": None, f"{SIDE_ABOVE}（押し目候補）": SIDE_ABOVE, f"{SIDE_BELOW}（戻り候補）": SIDE_BELOW}
TREND_OPTIONS = {"指定なし": None, "上向きのみ": "up", "下向きのみ": "down"}


@st.cache_data(show_spinner="データを読み込んでいます…")
def load(mtime: float):
    cache = data.load_cache()
    if cache is None:
        return None
    universe, prices, meta = cache
    return universe, prices, meta, compute_metrics(prices)


def cache_mtime() -> float:
    return data.META_PATH.stat().st_mtime if data.META_PATH.exists() else 0.0


def run_refresh() -> None:
    bar = st.progress(0.0, text="株価を取得しています（5分ほどかかります）…")
    try:
        data.refresh(lambda p: bar.progress(p, text=f"株価を取得しています… {p:.0%}"))
    except Exception as e:
        bar.empty()
        st.error(f"更新に失敗しました: {e}")
        return
    bar.empty()
    st.rerun()


def build_table(hits: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    t = hits.merge(universe, on="code", how="left")
    return pd.DataFrame(
        {
            "コード": t["code"],
            "銘柄名": t["name"],
            "市場": t["market"],
            "業種": t["sector"],
            "方向": t["side"],
            "終値": t["close"],
            "200日線": t["ma200"],
            "乖離率": t["gap_pct"],
            "距離": t["gap_atr"],
            "到達見込み": t["days_to_touch"],
            "線の傾き": t["slope_pct"],
            "前回タッチ": t["days_since_touch"],
            "売買代金": t["turnover"] / 1e8,
            "リンク": "https://finance.yahoo.co.jp/quote/" + t["code"] + ".T",
        }
    )


TABLE_COLUMNS = {
    "コード": st.column_config.TextColumn(width=50),
    "銘柄名": st.column_config.TextColumn(width=150),
    "市場": st.column_config.TextColumn(width=75),
    "業種": st.column_config.TextColumn(width=90),
    "方向": st.column_config.TextColumn(width=65),
    "終値": st.column_config.NumberColumn(format="%,.1f", width=65),
    "200日線": st.column_config.NumberColumn(format="%,.1f", width=65),
    "乖離率": st.column_config.NumberColumn("乖離(%)", format="%+.2f", width=60),
    "距離": st.column_config.NumberColumn("ATR", format="%.2f", width=50, help="200日線までの距離が、平均的な1日の値幅（ATR14）の何日分か"),
    "到達見込み": st.column_config.NumberColumn("到達(日)", format="%.0f", width=60, help="直近5営業日の接近ペースが続いた場合の到達見込み。あくまで目安。空欄は離れつつある銘柄"),
    "線の傾き": st.column_config.NumberColumn("傾き(%)", format="%+.2f", width=60, help="200日線の20営業日前からの変化率"),
    "前回タッチ": st.column_config.NumberColumn("前回(日前)", format="%d", width=70, help="高値〜安値が最後に200日線をまたいでからの営業日数。空欄は取得期間内にタッチなし"),
    "売買代金": st.column_config.NumberColumn("代金(億)", format="%,.1f", width=60, help="売買代金の直近20営業日平均（億円）"),
    "リンク": st.column_config.LinkColumn("", display_text="Yahoo!", width=50),
}


def price_chart(prices: pd.DataFrame, code: str) -> go.Figure:
    g = prices[prices["code"] == code].sort_values("date").copy()
    for w in (25, 75, MA_WINDOW):
        g[f"ma{w}"] = g["close"].rolling(w).mean()
    g = g.tail(CHART_DAYS)
    # 休場日の隙間が出ないよう、日付をカテゴリ軸で扱う
    x = g["date"].dt.strftime("%Y-%m-%d")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.8, 0.2])
    fig.add_trace(
        go.Candlestick(
            x=x, open=g["open"], high=g["high"], low=g["low"], close=g["close"], name="日足",
            # 陽線は白抜き。色だけに頼らず陰線と区別できるようにする
            increasing=dict(line=dict(color=COLOR_UP, width=1), fillcolor="#fcfcfb"),
            decreasing=dict(line=dict(color=COLOR_DOWN, width=1), fillcolor=COLOR_DOWN),
        ),
        row=1, col=1,
    )
    for col, name, color, width in (
        ("ma25", "25日線", COLOR_MA25, 1),
        ("ma75", "75日線", COLOR_MA75, 1),
        ("ma200", "200日線", COLOR_MA200, 2.5),
    ):
        fig.add_trace(
            go.Scatter(x=x, y=g[col], name=name, mode="lines", line=dict(color=color, width=width)),
            row=1, col=1,
        )
    fig.add_trace(
        go.Bar(x=x, y=g["volume"], name="出来高", marker_color=COLOR_VOLUME, marker_line_width=0),
        row=2, col=1,
    )
    fig.add_annotation(
        x=x.iloc[-1], y=g["ma200"].iloc[-1], text=f"200日線 {g['ma200'].iloc[-1]:,.1f}",
        xanchor="left", xshift=6, showarrow=False, font=dict(color=COLOR_MUTED, size=12), row=1, col=1,
    )
    fig.update_layout(
        height=560,
        margin=dict(l=8, r=120, t=8, b=8),
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fcfcfb",
        legend=dict(orientation="h", y=1.04, x=0),
        bargap=0.2,
    )
    fig.update_xaxes(type="category", nticks=8, gridcolor=COLOR_GRID, rangeslider_visible=False)
    fig.update_yaxes(gridcolor=COLOR_GRID, tickformat=",")
    fig.update_yaxes(title_text="株価（円）", row=1, col=1)
    fig.update_yaxes(title_text="出来高", row=2, col=1)
    return fig


st.set_page_config(page_title="200日線タッチ候補", page_icon="📈", layout="wide")
st.title("200日線タッチ候補")

loaded = load(cache_mtime())

with st.sidebar:
    if st.button("株価データを更新", type="primary", width="stretch"):
        run_refresh()
    if loaded:
        st.caption(f"最終更新: {loaded[2]['fetched_at'].replace('T', ' ')}")

    st.header("絞り込み")
    side_label = st.radio("接近の方向", list(SIDE_OPTIONS))
    max_atr = st.slider(
        "距離の上限（ATR）", 0.1, 5.0, 2.0, 0.1,
        help="200日線までの距離が、平均的な1日の値幅の何日分以内か",
    )
    max_pct = st.slider("乖離率の上限（%）", 0.5, 15.0, 5.0, 0.5)
    trend_label = st.radio("200日線の向き", list(TREND_OPTIONS), horizontal=True)
    markets = st.multiselect(
        "市場", ["プライム", "スタンダード", "グロース"], default=["プライム", "スタンダード", "グロース"]
    )
    min_turnover = st.number_input("売買代金の下限（億円・20日平均）", 0.0, 1000.0, 1.0, 0.5)
    approaching_only = st.checkbox("接近中の銘柄のみ", value=True, help="直近5営業日で200日線との距離が縮まっている銘柄")
    include_touched = st.checkbox("当日タッチ済みの銘柄も含める", value=False)

if loaded is None:
    st.info("株価データがまだありません。左の「株価データを更新」を押してください。")
    st.stop()

universe, prices, meta, metrics = loaded
hits = screen(
    metrics,
    max_atr=max_atr,
    max_pct=max_pct,
    side=SIDE_OPTIONS[side_label],
    ma_trend=TREND_OPTIONS[trend_label],
    min_turnover=min_turnover * 1e8,
    approaching_only=approaching_only,
    include_touched=include_touched,
)
table = build_table(hits, universe)
table = table[table["市場"].isin(markets)].reset_index(drop=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("株価の基準日", f"{metrics['last_date'].max():%Y/%m/%d}")
c2.metric("該当銘柄", f"{len(table):,}")
c3.metric(SIDE_ABOVE, f"{(table['方向'] == SIDE_ABOVE).sum():,}")
c4.metric(SIDE_BELOW, f"{(table['方向'] == SIDE_BELOW).sum():,}")

suspects = metrics[metrics["split_gap"]].merge(universe, on="code", how="left")
judged = len(metrics) - len(suspects)
excluded = meta["universe_count"] - len(metrics)
st.caption(
    f"対象 {meta['universe_count']:,}銘柄のうち {judged:,}銘柄を判定（{excluded:,}銘柄は上場から日が浅い・"
    f"取引停止中・取得失敗のため除外）。株価は Yahoo Finance の非公式データです。発注前に証券会社の画面で確認してください。"
)
if not suspects.empty:
    names = "、".join(suspects["code"] + " " + suspects["name"].fillna(""))
    st.warning(f"株式分割の調整漏れの疑いがあり、200日線を正しく計算できないため除外: {names}", icon="⚠️")

if table.empty:
    st.info("条件に合う銘柄がありません。左の条件を緩めてください。")
    st.stop()

st.caption("行を選ぶとチャートを表示します。列名を押すと並べ替えできます。")
selection = st.dataframe(
    table,
    column_config=TABLE_COLUMNS,
    hide_index=True,
    height=420,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    # 絞り込みが変わったら選択を解除する
    key=f"hits_{hash(tuple(table['コード']))}",
)
rows = selection.selection.rows
row = table.iloc[rows[0] if rows else 0]

st.subheader(f"{row['コード']} {row['銘柄名']}")
st.caption(
    f"{row['市場']}・{row['業種']} ／ 終値 {row['終値']:,.1f}円 ／ 200日線 {row['200日線']:,.1f}円 ／ "
    f"乖離率 {row['乖離率']:+.2f}% ／ {row['方向']}"
)
st.plotly_chart(price_chart(prices, row["コード"]), width="stretch")
