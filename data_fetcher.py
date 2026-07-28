"""
data_fetcher.py
================
Mengambil (1) daftar ticker S&P 500, dan (2) data harga OHLCV harian dari
Yahoo Finance (via library `yfinance`, gratis, delay ~15 menit) untuk
seluruh universe tsb.

CATATAN PENTING soal "update tiap 15 menit":
Formula AFL di project ini berbasis BAR HARIAN (Close vs SMA20, HHV 250 hari).
Sinyal yang "sah" secara definisi AFL baru final setelah candle harian
DITUTUP (market close). Supaya dashboard tetap bisa terasa "hidup" tiap 15
menit selama jam bursa, kita buat bar HARI INI yang MASIH BERJALAN (preview)
dari data intraday: Open = open sesi ini, High/Low = agregat sejauh ini,
Close = harga terakhir (delay 15 menit), Volume = volume sejauh ini.
Bar preview ini ditempel di baris terakhir data harian sebelum dievaluasi,
lalu ditandai preview=True. Setelah market tutup, jalankan sekali lagi supaya
bar tsb "mengeras" jadi bar harian final (preview=False).
"""

import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UNIVERSE_CACHE_PATH = "data/sp500_universe.csv"


def get_sp500_universe(refresh: bool = False) -> pd.DataFrame:
    """
    Ambil daftar ticker + sektor S&P 500.

    Strategi:
    - Kalau ada cache lokal (data/sp500_universe.csv) dan refresh=False -> pakai cache.
      (Direkomendasikan: refresh cache ini cukup 1x/minggu lewat workflow terpisah,
      karena anggota S&P 500 jarang berubah dan scraping Wikipedia tiap 15 menit
      itu boros & rawan diblokir.)
    - Kalau tidak ada cache / refresh=True -> scrape tabel Wikipedia sekali, simpan ke cache.
    """
    import os

    if not refresh and os.path.exists(UNIVERSE_CACHE_PATH):
        return pd.read_csv(UNIVERSE_CACHE_PATH)

    tables = pd.read_html(SP500_WIKI_URL)
    sp500 = tables[0][["Symbol", "Security", "GICS Sector"]].copy()
    sp500.columns = ["ticker", "name", "sector"]
    # yfinance pakai tanda '-' bukan '.' untuk share class, mis. BRK.B -> BRK-B
    sp500["ticker"] = sp500["ticker"].str.replace(".", "-", regex=False)

    os.makedirs(os.path.dirname(UNIVERSE_CACHE_PATH), exist_ok=True)
    sp500.to_csv(UNIVERSE_CACHE_PATH, index=False)
    return sp500


def fetch_daily_history(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    """
    Download data harian OHLCV untuk banyak ticker SEKALIGUS (1 request batch,
    bukan loop per-ticker) supaya lebih cepat & lebih hemat kuota/risiko rate-limit.

    period="2y": cukup untuk mengisi rolling window 250 hari (LookbackResistance)
    + MA20 + beberapa bulan buffer di depannya, supaya sinyal di bar terakhir valid.
    """
    raw = yf.download(
        tickers=tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,   # Close/High/Low disesuaikan split & dividen (konsisten)
        threads=True,
        progress=False,
    )

    result: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                df = raw.copy()
            else:
                df = raw[t].copy()
            df = df.dropna(how="all")
            if df.empty or len(df) < 60:
                continue  # data terlalu pendek (ticker baru IPO / delisted / salah simbol)
            result[t] = df[["Open", "High", "Low", "Close", "Volume"]]
        except (KeyError, Exception):
            continue
    return result


def fetch_today_preview_bar(ticker: str) -> pd.Series | None:
    """
    Bentuk 1 baris "bar hari ini yang masih berjalan" dari data intraday
    15 menit (delay Yahoo Finance ~15 menit). Dipakai untuk mode preview
    saat market masih buka. Return None kalau data tidak tersedia
    (mis. market tutup / hari libur / ticker bermasalah).
    """
    try:
        intraday = yf.download(
            tickers=ticker,
            period="1d",
            interval="15m",
            auto_adjust=True,
            progress=False,
        )
        if intraday.empty:
            return None
        today_rows = intraday  # yfinance sudah membatasi ke sesi terakhir saat period="1d"
        bar = pd.Series({
            "Open": today_rows["Open"].iloc[0],
            "High": today_rows["High"].max(),
            "Low": today_rows["Low"].min(),
            "Close": today_rows["Close"].iloc[-1],
            "Volume": today_rows["Volume"].sum(),
        }, name=pd.Timestamp(datetime.now(timezone.utc).date()))
        return bar
    except Exception:
        return None


def with_preview_bar(daily_df: pd.DataFrame, preview_bar: pd.Series | None) -> tuple[pd.DataFrame, bool]:
    """
    Tempel/replace baris terakhir dengan bar preview hari ini kalau ada.
    Return (df_gabungan, is_preview).
    """
    if preview_bar is None:
        return daily_df, False

    df = daily_df.copy()
    last_date = df.index[-1].date()
    preview_date = preview_bar.name.date()

    if last_date == preview_date:
        # bar hari ini SUDAH tercatat sebagai bar harian final -> jangan overwrite
        return df, False

    df.loc[preview_bar.name] = preview_bar
    return df, True
