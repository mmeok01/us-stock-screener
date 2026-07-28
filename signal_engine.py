"""
signal_engine.py
=================
Terjemahan 1:1 dari logika AFL "Breakout_ATH_SMA20_Stoploss_3.afl" ke Python.

------------------------------------------------------------------------------
PADANAN FUNGSI AFL -> PYTHON (dipakai di modul ini)
------------------------------------------------------------------------------
AFL                                   Python (pandas / numpy)
-------------------------------------  -------------------------------------
Param(...)                            konstanta / argumen fungsi (lihat SignalParams)
ParamToggle(...)                      boolean (True/False)
HHV(High, N)                          High.rolling(N).max()
Ref(X, -1)                            X.shift(1)   -> nilai bar SEBELUMNYA
    Ref(HHV(High,N), -1)              High.rolling(N).max().shift(1)
                                       = HHV dari N bar SEBELUM bar sekarang
                                         (bar sekarang TIDAK ikut dihitung)
MA(X, N)                              X.rolling(N).mean()   (Simple Moving Average)
IIf(cond, a, b)                       np.where(cond, a, b)  atau  a if cond else b
AND / OR (array)                      &  /  |   (elementwise, WAJIB pakai kurung)
Null                                  np.nan
Nz(X, ganti)                          np.where(np.isnan(X), ganti, X)
for (i=1; i<BarCount; i++) { ... }    for i in range(1, len(df)): ...
Buy[i] = 1 / Sell[i] = 1              array integer 0/1 (lebih gampang dianalisis di Python
                                       drpd Buy/Sell boolean khas AmiBroker)

------------------------------------------------------------------------------
KENAPA TETAP PAKAI LOOP (bukan full-vectorized)?
------------------------------------------------------------------------------
Sama seperti versi AFL aslinya (yang sengaja pakai for-loop, bukan
IIf/ValueWhen), logika Buy/Sell di sini BERGANTUNG PADA STATUS POSISI:
  - Sinyal Buy tidak boleh "retrigger" selama posisi masih terbuka.
  - StopLevel dikunci ke Low candle BELI yang sebenarnya (bukan ikut update
    seperti trailing stop).
  - Exit (stoploss atau tembus SMA20) hanya dicek SELAMA posisi terbuka.
Ini disebut "path dependent" -> tidak bisa dihitung per-bar secara independen,
jadi loop sekuensial adalah cara yang BENAR (bukan cara yang malas), dan pandas
tidak dipaksakan untuk vectorize bagian ini supaya logika tetap identik dengan
AFL aslinya. Indikator yang TIDAK bergantung status posisi (Resistance, SMA20,
filter volume) tetap dihitung vectorized (rolling) karena itu sudah benar &
lebih cepat.
"""

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class SignalParams:
    """Persis field 'Param(...)' / 'ParamToggle(...)' di baris 15-18 file AFL."""
    lookback_resistance: int = 250   # Param("Lookback Resistance/ATH (bar)", 250, ...)
    use_volume_filter: bool = False  # ParamToggle("Filter Volume (breakout valid)", "Tidak|Ya", 0)
    vol_multiplier: float = 1.5      # Param("Syarat Volume > MA20 Volume x", 1.5, ...)
    ma_period: int = 20              # Param("Periode SMA Exit", 20, ...)


REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def compute_signals(df: pd.DataFrame, params: SignalParams = SignalParams()) -> pd.DataFrame:
    """
    Input : df dengan kolom Open, High, Low, Close, Volume (index = tanggal, urut naik).
    Output: df yang sama + kolom hasil perhitungan AFL:
            Resistance, SMA_Exit, Buy, Sell, StopLevel, EntryPrice, SellPrice,
            StopLossPct, ReturnPct

    Setiap baris komentar merujuk ke baris asli di file .afl.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom hilang: {missing}")

    df = df.copy()
    n = len(df)

    # ---- baris 21: Resistance = Ref(HHV(High, LookbackResistance), -1) ----
    # HHV(High,N)  -> rolling max N bar TERMASUK bar sekarang
    # Ref(...,-1)  -> geser mundur 1 bar -> jadi highest high dari N bar SEBELUM
    #                 bar sekarang (breakout dibandingkan ke resistance yang
    #                 "sudah terbentuk", bukan ikut High hari ini)
    resistance = df["High"].rolling(params.lookback_resistance).max().shift(1)

    # ---- baris 24: VolumeOK = IIf(UseVolumeFilter, Volume > MA(Volume,20)*Mult, True) ----
    vol_ma20 = df["Volume"].rolling(20).mean()
    if params.use_volume_filter:
        volume_ok = df["Volume"] > (vol_ma20 * params.vol_multiplier)
    else:
        volume_ok = pd.Series(True, index=df.index)

    # ---- baris 25: BreakoutValid = Close > Resistance AND VolumeOK ----
    breakout_valid = (df["Close"] > resistance) & volume_ok
    breakout_valid = breakout_valid.fillna(False)

    # ---- baris 26: SMA20 = MA(Close, MAPeriod) ----
    sma_exit = df["Close"].rolling(params.ma_period).mean()

    # Ambil sebagai numpy array supaya loop di bawah cepat (setara array AFL)
    close = df["Close"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    open_ = df["Open"].to_numpy(dtype=float)
    breakout_arr = breakout_valid.to_numpy(dtype=bool)
    sma_arr = sma_exit.to_numpy(dtype=float)

    buy = np.zeros(n, dtype=int)
    sell = np.zeros(n, dtype=int)
    stop_level = np.full(n, np.nan)
    entry_price_arr = np.full(n, np.nan)
    sell_price_arr = np.full(n, np.nan)

    # ---- baris 35-37: InPosition=False; EntryLow=0; EntryClose=0 ----
    in_position = False
    entry_low = 0.0
    entry_close = 0.0

    # ---- baris 39-72: for (i=1; i<BarCount; i++) { ... } ----
    for i in range(1, n):
        this_bar_has_position = in_position  # baris 41: ThisBarHasPosition = InPosition

        if not in_position:  # baris 43: if (NOT InPosition)
            if breakout_arr[i]:  # baris 45: if (BreakoutValid[i])
                buy[i] = 1
                in_position = True
                entry_low = low[i]
                entry_close = close[i]
                this_bar_has_position = True
        else:  # baris 54: else (sedang posisi terbuka)
            stop_hit = low[i] < entry_low  # baris 56
            sell_ma = (not np.isnan(sma_arr[i])) and (close[i] < sma_arr[i])  # baris 57

            if stop_hit or sell_ma:  # baris 59
                sell[i] = 1
                in_position = False
                # baris 63: SellPrice = IIf(StopHit, Min(Open, EntryLow), Close)
                sell_price_arr[i] = min(open_[i], entry_low) if stop_hit else close[i]

        if this_bar_has_position:  # baris 67
            stop_level[i] = entry_low
            entry_price_arr[i] = entry_close

    df["Resistance"] = resistance
    df["SMA_Exit"] = sma_exit
    df["Buy"] = buy
    df["Sell"] = sell
    df["StopLevel"] = stop_level
    df["EntryPrice"] = entry_price_arr

    # ---- baris 74-75: BuyPrice=Close; SellPrice=Nz(SellPriceArr, Close) ----
    df["SellPrice"] = np.where(~np.isnan(sell_price_arr), sell_price_arr, close)

    # ---- baris 78-79: StopLossPct & ReturnPct ----
    df["StopLossPct"] = (df["EntryPrice"] - df["StopLevel"]) / df["EntryPrice"] * 100
    df["ReturnPct"] = (df["SellPrice"] - df["EntryPrice"]) / df["EntryPrice"] * 100

    df.attrs["still_in_position"] = in_position  # status akhir (dipakai screener)
    df.attrs["open_entry_low"] = entry_low
    df.attrs["open_entry_close"] = entry_close
    return df


def latest_signal(df_signals: pd.DataFrame, preview: bool = False) -> dict:
    """
    Ambil status sinyal pada BAR TERAKHIR saja (dipakai screener untuk
    menentukan status "hari ini" per ticker).

    preview=True artinya bar terakhir adalah bar intraday yang BELUM close
    (harga masih bisa berubah sampai market tutup) -> ditandai sebagai
    'BUY (preview)' / 'SELL (preview)', bukan sinyal final.
    """
    if len(df_signals) == 0:
        return {"signal": "NONE"}

    last = df_signals.iloc[-1]
    suffix = " (preview)" if preview else ""

    if last["Buy"] == 1:
        signal = "BUY" + suffix
    elif last["Sell"] == 1:
        signal = "SELL" + suffix
    elif not np.isnan(last["StopLevel"]):
        # posisi masih terbuka dari hari-hari sebelumnya, tidak ada Buy/Sell baru hari ini
        signal = "HOLD"
    else:
        signal = "NONE"

    return {
        "signal": signal,
        "date": df_signals.index[-1],
        "close": round(float(last["Close"]), 2),
        "resistance": None if np.isnan(last["Resistance"]) else round(float(last["Resistance"]), 2),
        "sma_exit": None if np.isnan(last["SMA_Exit"]) else round(float(last["SMA_Exit"]), 2),
        "stop_level": None if np.isnan(last["StopLevel"]) else round(float(last["StopLevel"]), 2),
        "stop_loss_pct": None if np.isnan(last["StopLossPct"]) else round(float(last["StopLossPct"]), 2),
        "return_pct": (
            round(float(last["ReturnPct"]), 2)
            if (last["Sell"] == 1 and not np.isnan(last["ReturnPct"]))
            else None
        ),
    }
