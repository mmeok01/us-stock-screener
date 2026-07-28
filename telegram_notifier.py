"""
telegram_notifier.py
=====================
STATUS: SUDAH DISIAPKAN, BELUM AKTIF.

Modul ini SENGAJA dibuat "aman secara default": selama environment variable
TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID belum diisi, semua fungsi di sini jadi
no-op (tidak melakukan apa-apa, tidak error). Jadi modul ini BOLEH sudah
di-import & dipanggil dari screener.py sekarang, tanpa risiko tiba-tiba
mengirim pesan ke Telegram sebelum kamu siap.

CARA MENGAKTIFKAN (nanti, kalau sudah siap):
  1. Chat @BotFather di Telegram -> /newbot -> catat token yang diberikan.
  2. Kirim 1 pesan apa saja ke bot kamu, lalu buka:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     cari angka "chat":{"id": ...} -> itu CHAT_ID kamu.
  3. Di GitHub repo: Settings -> Secrets and variables -> Actions -> New repository secret
     tambahkan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID.
  4. Di .github/workflows/screener.yml, tambahkan di bagian `env:` step
     "Jalankan screener":
         env:
           TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
           TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
  Setelah itu, notifikasi otomatis aktif tanpa perlu ubah kode lagi.
"""

import os
import pandas as pd
import requests

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> None:
    if not is_configured():
        return  # no-op sampai secrets diisi
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    try:
        requests.post(
            TELEGRAM_API_URL.format(token=token),
            data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"[WARN] Gagal kirim notifikasi Telegram: {e}")


def detect_new_signals(current_df: pd.DataFrame, previous_log_path: str) -> pd.DataFrame:
    """
    Bandingkan hasil run SEKARANG dengan histori (signal_log.csv) untuk
    menemukan sinyal yang BENAR-BENAR BARU (ticker+signal+date belum pernah
    tercatat sebelumnya) -> supaya Telegram tidak spam mengirim sinyal yang
    sama berulang-ulang tiap 15 menit.
    """
    if not os.path.exists(previous_log_path) or current_df.empty:
        return current_df

    prev = pd.read_csv(previous_log_path)
    if prev.empty:
        return current_df

    key_cols = ["ticker", "signal", "date"]
    prev_keys = set(map(tuple, prev[key_cols].astype(str).values))
    current_df = current_df.copy()
    current_df["_key"] = list(map(tuple, current_df[key_cols].astype(str).values))
    new_signals = current_df[~current_df["_key"].isin(prev_keys)].drop(columns="_key")
    return new_signals


def notify_new_signals(current_df: pd.DataFrame, previous_log_path: str) -> None:
    if not is_configured():
        return  # SENGAJA tidak berbuat apa-apa selama belum diaktifkan (lihat header file)

    new_signals = detect_new_signals(current_df, previous_log_path)
    if new_signals.empty:
        return

    for _, row in new_signals.iterrows():
        emoji = "🟢" if "BUY" in row["signal"] else ("🔴" if "SELL" in row["signal"] else "⚪")
        msg = (
            f"{emoji} *{row['signal']}* — *{row['ticker']}* ({row.get('sector', '-')})\n"
            f"Close: {row['close']} | Resistance: {row.get('resistance', '-')} | "
            f"SMA20: {row.get('sma_exit', '-')}\n"
            f"Tanggal: {row['date']}"
        )
        send_telegram_message(msg)
