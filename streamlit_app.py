"""
streamlit_app.py
=================
Dashboard web. Jalankan lokal dengan:
    streamlit run streamlit_app.py
Deploy gratis di Streamlit Community Cloud (lihat README.md bagian Deploy).

App ini HANYA membaca file results/signals.json (dibuat oleh screener.py).
Ia tidak menghitung ulang sinyal sendiri -> ringan & cepat, cocok untuk free tier.
"""

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

RESULTS_JSON_PATH = "results/signals.json"

st.set_page_config(page_title="US Stock Screener - Breakout ATH", layout="wide")


@st.cache_data(ttl=60)  # cache 60 detik, cukup untuk mengurangi beban baca file berulang
def load_results():
    try:
        with open(RESULTS_JSON_PATH) as f:
            payload = json.load(f)
    except FileNotFoundError:
        return None
    df = pd.DataFrame(payload["signals"])
    return payload["generated_at_utc"], payload["params"], df


st.title("🇺🇸 US Stock Screener — Breakout ATH / SMA20 / Stoploss")
st.caption(
    "Sumber data: Yahoo Finance (delay ±15 menit). "
    "Sinyal ditandai **(preview)** jika bar hari ini masih berjalan (belum close)."
)

loaded = load_results()

if loaded is None:
    st.warning(
        "Belum ada hasil screening (results/signals.json tidak ditemukan). "
        "Jalankan `python screener.py` dulu, atau tunggu run GitHub Actions berikutnya."
    )
    st.stop()

generated_at, params, df = loaded

# ---- Header info ----
col1, col2, col3 = st.columns(3)
generated_dt = datetime.fromisoformat(generated_at)
age_minutes = (datetime.now(timezone.utc) - generated_dt).total_seconds() / 60
col1.metric("Update terakhir (UTC)", generated_dt.strftime("%Y-%m-%d %H:%M"))
col2.metric("Umur data", f"{age_minutes:.0f} menit lalu")
col3.metric("Jumlah sinyal aktif", len(df))

if age_minutes > 30:
    st.info(
        "⏱️ Data lebih lama dari 30 menit. Kemungkinan market sedang tutup, "
        "atau scheduler (GitHub Actions) belum jalan lagi — cek README bagian Troubleshooting."
    )

with st.expander("Parameter strategi yang dipakai"):
    st.json(params)

if df.empty:
    st.success("Tidak ada sinyal BUY/SELL/HOLD saat ini di seluruh universe S&P 500.")
    st.stop()

# ---- Filter ----
st.subheader("Filter")
f1, f2, f3 = st.columns(3)

signal_types = sorted(df["signal"].unique().tolist())
selected_signals = f1.multiselect("Jenis sinyal", signal_types, default=signal_types)

sectors = sorted(df["sector"].dropna().unique().tolist())
selected_sectors = f2.multiselect("Sektor", sectors, default=sectors)

search = f3.text_input("Cari ticker", "")

filtered = df[df["signal"].isin(selected_signals) & df["sector"].isin(selected_sectors)]
if search:
    filtered = filtered[filtered["ticker"].str.contains(search.upper())]

# ---- Sort ----
sort_options = {
    "Ticker (A-Z)": ("ticker", True),
    "Tanggal sinyal (terbaru)": ("date", False),
    "Return % (untuk SELL)": ("return_pct", False),
    "Stoploss % (untuk BUY/HOLD)": ("stop_loss_pct", False),
}
sort_choice = st.selectbox("Urutkan berdasarkan", list(sort_options.keys()))
sort_col, ascending = sort_options[sort_choice]
if sort_col in filtered.columns:
    filtered = filtered.sort_values(sort_col, ascending=ascending, na_position="last")

# ---- Tabel ----
st.subheader(f"Hasil ({len(filtered)} ticker)")


def highlight_signal(row):
    color = ""
    if "BUY" in row["signal"]:
        color = "background-color: #103a1f"
    elif "SELL" in row["signal"]:
        color = "background-color: #3a1010"
    elif row["signal"] == "HOLD":
        color = "background-color: #1a1a1a"
    return [color] * len(row)


display_cols = [
    "ticker", "sector", "signal", "date", "close",
    "resistance", "sma_exit", "stop_level", "stop_loss_pct", "return_pct",
]
display_cols = [c for c in display_cols if c in filtered.columns]

st.dataframe(
    filtered[display_cols].style.apply(highlight_signal, axis=1),
    use_container_width=True,
    height=500,
)

st.download_button(
    "⬇️ Download hasil (CSV)",
    filtered[display_cols].to_csv(index=False).encode(),
    file_name=f"signals_{generated_dt.strftime('%Y%m%d_%H%M')}.csv",
)

st.caption(
    "⚠️ Ini alat bantu screening, BUKAN rekomendasi investasi. "
    "Data delay ~15 menit dari Yahoo Finance dan bisa saja terlambat/gagal update "
    "(lihat keterbatasan di README)."
)
