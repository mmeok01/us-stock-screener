"""
screener.py
===========
Orkestrator utama. Dijalankan oleh:
  - GitHub Actions (terjadwal tiap 15 menit saat jam bursa AS), ATAU
  - manual: `python screener.py` dari laptop kamu.

Alur:
  1. Ambil universe S&P 500 (dari cache lokal data/sp500_universe.csv)
  2. Download data harian semua ticker (1 batch request)
  3. (Opsional) tempel bar preview intraday hari ini kalau market sedang buka
  4. Jalankan compute_signals() -> ambil status sinyal bar terakhir
  5. Simpan hasil ke results/signals.json (dibaca oleh dashboard Streamlit)
     dan tambahkan ke results/signal_log.csv (histori, untuk basis notifikasi
     Telegram nanti: "sinyal baru" = muncul di run sekarang tapi tidak di run
     sebelumnya).
"""

import json
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from signal_engine import compute_signals, latest_signal, SignalParams
from data_fetcher import (
    get_sp500_universe,
    fetch_daily_history,
    fetch_today_preview_bar,
    with_preview_bar,
)
from telegram_notifier import notify_new_signals  # aman: no-op selama secrets belum diisi

RESULTS_JSON_PATH = "results/signals.json"
SIGNAL_LOG_CSV_PATH = "results/signal_log.csv"

# Parameter default SAMA PERSIS dengan nilai default di file AFL (baris 15-18).
# Ganti di sini kalau kamu mengubah Parameters window di AmiBroker.
PARAMS = SignalParams(
    lookback_resistance=250,
    use_volume_filter=False,
    vol_multiplier=1.5,
    ma_period=20,
)


def is_market_open_now() -> bool:
    """Cek kasar apakah sesi reguler NYSE/Nasdaq (09:30-16:00 ET, Senin-Jumat)
    sedang berlangsung. TIDAK memperhitungkan hari libur bursa AS (mis. Thanksgiving,
    Natal) -- itu keterbatasan yang disengaja supaya kode tetap simpel untuk
    pemula. Kalau workflow kebetulan jalan pas hari libur, hasilnya cuma
    "preview" yang identik dengan bar harian terakhir yang sudah ada -> tidak
    berbahaya, cuma sedikit kerja sia-sia."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:  # Sabtu/Minggu
        return False
    open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now_et <= close_t


def run_screener(tickers: list[str] | None = None) -> pd.DataFrame:
    universe = get_sp500_universe()
    if tickers is None:
        tickers = universe["ticker"].tolist()
    sector_map = dict(zip(universe["ticker"], universe["sector"]))

    market_open = is_market_open_now()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Market open (ET)? {market_open}")
    print(f"Mengambil data harian untuk {len(tickers)} ticker ...")

    daily_data = fetch_daily_history(tickers, period="2y")
    print(f"Berhasil mengambil {len(daily_data)}/{len(tickers)} ticker.")

    rows = []
    for i, (ticker, df) in enumerate(daily_data.items(), start=1):
        try:
            df_eval = df
            is_preview = False

            if market_open:
                preview_bar = fetch_today_preview_bar(ticker)
                df_eval, is_preview = with_preview_bar(df, preview_bar)
                time.sleep(0.05)  # jeda kecil antar-request, sopan ke server Yahoo

            signals = compute_signals(df_eval, PARAMS)
            info = latest_signal(signals, preview=is_preview)

            if info["signal"] == "NONE":
                continue  # tidak perlu dicatat kalau memang tidak ada sinyal/posisi

            rows.append({
                "ticker": ticker,
                "sector": sector_map.get(ticker, "Unknown"),
                **info,
            })
        except Exception as e:
            print(f"  [WARN] Gagal proses {ticker}: {e}")
            continue

        if i % 50 == 0:
            print(f"  ... {i}/{len(daily_data)} ticker diproses")

    result_df = pd.DataFrame(rows)
    return result_df


def save_results(result_df: pd.DataFrame) -> None:
    import os
    os.makedirs("results", exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at_utc": timestamp,
        "params": {
            "lookback_resistance": PARAMS.lookback_resistance,
            "use_volume_filter": PARAMS.use_volume_filter,
            "vol_multiplier": PARAMS.vol_multiplier,
            "ma_period": PARAMS.ma_period,
        },
        "signals": json.loads(result_df.to_json(orient="records", date_format="iso")),
    }
    with open(RESULTS_JSON_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Tersimpan: {RESULTS_JSON_PATH} ({len(result_df)} baris sinyal)")

    # Notifikasi Telegram untuk sinyal yang BENAR-BENAR BARU (dibanding log sebelumnya).
    # Tidak melakukan apa-apa selama TELEGRAM_BOT_TOKEN/CHAT_ID belum diset
    # (lihat telegram_notifier.py untuk cara mengaktifkan).
    notify_new_signals(result_df, SIGNAL_LOG_CSV_PATH)

    # Log historis (dipakai lagi sebagai pembanding di run berikutnya)
    log_df = result_df.copy()
    log_df.insert(0, "run_timestamp_utc", timestamp)
    header_needed = not os.path.exists(SIGNAL_LOG_CSV_PATH)
    log_df.to_csv(SIGNAL_LOG_CSV_PATH, mode="a", header=header_needed, index=False)


if __name__ == "__main__":
    # Untuk uji cepat/lokal, bisa batasi jumlah ticker lewat argumen, mis:
    #   python screener.py AAPL MSFT NVDA
    limit_tickers = sys.argv[1:] or None
    df = run_screener(limit_tickers)
    save_results(df)
    if len(df):
        print(df[["ticker", "signal", "close", "date"]].to_string(index=False))
    else:
        print("Tidak ada sinyal BUY/SELL/HOLD saat ini.")
