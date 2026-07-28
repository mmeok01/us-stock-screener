# US Stock Screener — Breakout ATH / SMA20 / Stoploss

Screener saham S&P 500 otomatis berbasis formula AFL kamu (`Breakout_ATH_SMA20_Stoploss_3.afl`),
jalan gratis 100% (data Yahoo Finance, compute GitHub Actions, dashboard Streamlit Community Cloud).

---

## 0. Asumsi penting yang perlu kamu tahu dulu

Formula AFL kamu berbasis **bar harian** (Close vs SMA20, HHV 250 hari/bar). Sinyal BUY/SELL
dalam definisi aslinya baru **final setelah candle harian ditutup** (market close 16:00 ET).

Karena kamu minta update tiap 15 menit, sistem ini punya 2 mode:

| Mode | Kapan | Sifat |
|---|---|---|
| **Preview** | Selama jam bursa (09:30–16:00 ET) | Pakai harga "sejauh ini" hari ini (delay ~15 menit dari Yahoo). Bisa berubah sampai market tutup. Ditandai `(preview)` di dashboard. |
| **Final** | Setelah market tutup | Bar hari ini sudah jadi bar harian resmi. Sinyal tidak berubah lagi sampai bar besok. |

Anggap sinyal **(preview)** sebagai "sedang menuju sinyal", bukan konfirmasi final — persis seperti kalau kamu membuka chart AmiBroker di tengah hari saat candle belum close.

---

## 1. Arsitektur Sistem

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐     ┌─────────────────┐
│  Yahoo Finance   │     │  GitHub Actions   │     │  results/           │     │  Streamlit       │
│  (yfinance,      │────▶│  screener.py      │────▶│  signals.json       │────▶│  Community Cloud │
│  delay ~15 menit)│     │  (jadwal 15 menit,│     │  signal_log.csv     │     │  (dashboard web, │
│                  │     │   gratis)         │     │  (di-commit ke Git) │     │   gratis)        │
└─────────────────┘     └────────┬─────────┘     └────────────────────┘     └─────────────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ telegram_notifier │  ← sudah disiapkan,
                         │ (nonaktif sampai  │     BELUM diaktifkan
                         │  secrets diisi)   │
                         └──────────────────┘
```

**Kenapa arsitekturnya seperti ini (dipisah compute vs tampilan)?**
Streamlit Community Cloud tidak punya "cron job" bawaan yang bisa jalan sendiri di background
tanpa ada yang buka app-nya. Jadi *compute* (ambil data + hitung sinyal) dipisah ke **GitHub Actions**
yang punya scheduler gratis sungguhan, hasilnya disimpan sebagai file `results/signals.json` di
repo yang sama, lalu **dashboard Streamlit hanya membaca file itu** (ringan, cepat, tidak
menghitung ulang tiap ada orang buka dashboard).

## 2. Struktur folder

```
us_screener/
├── signal_engine.py        # Terjemahan AFL -> Python (LOGIKA INTI, baca komentarnya)
├── data_fetcher.py         # Ambil universe S&P 500 + data harga dari Yahoo Finance
├── screener.py              # Orkestrator: loop semua ticker, simpan hasil
├── telegram_notifier.py     # Notifikasi Telegram (siap pakai, belum aktif)
├── streamlit_app.py         # Dashboard web
├── requirements.txt
├── data/sp500_universe.csv  # Cache daftar ticker (dibuat otomatis saat pertama jalan)
├── results/signals.json     # Output terbaru (dibaca dashboard)
├── results/signal_log.csv   # Histori semua sinyal (basis notifikasi Telegram)
└── .github/workflows/screener.yml  # Scheduler gratis (GitHub Actions)
```

## 3. Ringkasan padanan AFL → Python

Penjelasan detail + rujukan baris AFL asli ada sebagai **komentar di dalam `signal_engine.py`**.
Ringkasannya:

| AFL | Python |
|---|---|
| `HHV(High, N)` | `High.rolling(N).max()` |
| `Ref(X, -1)` | `X.shift(1)` |
| `MA(X, N)` | `X.rolling(N).mean()` |
| `IIf(cond, a, b)` | `np.where(cond, a, b)` |
| `Nz(X, ganti)` | `X.fillna(ganti)` |
| loop `for(i=1;i<BarCount;i++)` | `for i in range(1, len(df))` (dipertahankan sebagai loop, **bukan** di-vectorize, karena logikanya *path-dependent*: status posisi, level stoploss yang terkunci ke Low candle beli, dan aturan "tidak boleh retrigger" hanya bisa dihitung benar secara sekuensial — sama seperti alasan versi AFL aslinya juga sengaja pakai loop, bukan `IIf`/`ValueWhen`) |

Logika ini sudah diuji dengan data sintetis untuk 2 skenario (exit via stoploss, dan exit via
Close < SMA20) untuk memastikan hasilnya identik dengan alur di file AFL, termasuk kasus kedua
kondisi exit terjadi bersamaan (prioritas: harga stoploss yang dipakai, sama seperti `IIf(StopHit, Min(Open,EntryLow), Close)`).

## 4. Menjalankan di laptop (lokal) dulu — direkomendasikan sebelum deploy

1. Install Python 3.11+ dari [python.org](https://www.python.org/downloads/) (pemula: centang "Add Python to PATH" saat install di Windows).
2. Download/`git clone` folder project ini, lalu buka terminal di folder tsb.
3. Install dependensi:
   ```
   pip install -r requirements.txt
   ```
4. Uji dengan beberapa ticker dulu (lebih cepat daripada 500 sekaligus):
   ```
   python screener.py AAPL MSFT NVDA TSLA
   ```
   Ini akan membuat `results/signals.json`. Kalau tidak ada sinyal, itu normal (breakout ATH
   250-hari tidak setiap hari terjadi).
5. Jalankan dashboard:
   ```
   streamlit run streamlit_app.py
   ```
   Buka `http://localhost:8501` di browser.
6. Kalau sudah yakin jalan, coba tanpa argumen (seluruh S&P 500 — bisa makan waktu beberapa
   menit karena ~500 ticker):
   ```
   python screener.py
   ```

## 5. Deploy gratis — step by step

### Langkah A — Push ke GitHub
1. Buat akun GitHub kalau belum punya ([github.com](https://github.com)).
2. Buat repo baru, **pilih Public** (lihat kenapa di bagian Keterbatasan #1 di bawah).
3. Upload seluruh isi folder `us_screener/` ke repo tsb (lewat web GitHub "Add file → Upload
   files", atau `git init && git add . && git commit -m "init" && git push` kalau sudah kenal git).

### Langkah B — Aktifkan scheduler (GitHub Actions)
Workflow-nya (`.github/workflows/screener.yml`) sudah otomatis aktif begitu file itu ada di
repo kamu — GitHub akan menjalankan `screener.py` setiap 15 menit selama jam bursa AS (Senin–Jumat).
Untuk mengecek/mengetes manual:
1. Buka tab **Actions** di repo GitHub kamu.
2. Klik workflow **"Run US Stock Screener"** → tombol **"Run workflow"** (ini `workflow_dispatch`,
   trigger manual, tidak perlu nunggu jadwal).
3. Setelah selesai (~1-3 menit tergantung jumlah ticker), cek apakah `results/signals.json`
   ter-update di repo (lihat tab "Code").

**Penting:** Workflow butuh izin menulis (commit) balik ke repo. Kalau push gagal karena
permission, buka **Settings → Actions → General → Workflow permissions**, pilih
**"Read and write permissions"**, lalu Save.

### Langkah C — Deploy dashboard (Streamlit Community Cloud)
1. Buka [share.streamlit.io](https://share.streamlit.io), sign in pakai akun GitHub kamu.
2. Klik **"New app"**, pilih repo dan branch kamu, isi **Main file path** = `streamlit_app.py`.
3. Klik **Deploy**. Tunggu 1-2 menit, dashboard akan online di URL seperti
   `https://<nama-app>.streamlit.app`.
4. Setiap kali GitHub Actions commit `results/signals.json` baru, dashboard akan otomatis
   menampilkan data terbaru saat halaman di-refresh (app di-restart otomatis oleh Streamlit Cloud
   ketika ada commit baru ke repo — ini gratis, tapi baca catatan rate-limit di bagian Keterbatasan #4).

## 6. Mengaktifkan notifikasi Telegram (nanti, opsional)

Modul `telegram_notifier.py` **sudah ditulis lengkap tapi otomatis nonaktif** (no-op) sampai kamu
mengisi 2 secrets di GitHub. Langkahnya:
1. Chat **@BotFather** di Telegram → `/newbot` → catat **token**-nya.
2. Kirim 1 pesan apa saja ke bot barumu, lalu buka di browser:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → cari `"chat":{"id": ...}` → itu **chat_id** kamu.
3. Di repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**,
   tambahkan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`.
4. Di `.github/workflows/screener.yml`, tambahkan `env:` di bawah step **"Jalankan screener"**:
   ```yaml
      - name: Jalankan screener
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python screener.py
   ```
5. Push perubahan itu. Selesai — sekarang tiap ada sinyal BUY/SELL **baru** (belum pernah
   tercatat sebelumnya), bot akan mengirim pesan otomatis. Tidak perlu ubah kode Python sama sekali.

## 7. Keterbatasan setup gratis ini (biar ekspektasi realistis)

1. **Repo harus Public untuk GitHub Actions gratis tanpa batas.** Repo Private tetap bisa,
   tapi jatah gratisnya cuma 2.000 menit/bulan (Free plan) — dengan run tiap 15 menit x jam
   bursa x 21 hari kerja, kamu bisa saja melebihi itu tergantung berapa lama tiap run (jumlah
   ticker). Konsekuensi Public: kode & strategi (termasuk formula breakout kamu) bisa dilihat
   siapa saja. Kalau strategi ini sensitif buat kamu, pertimbangkan repo Private + kurangi
   frekuensi (mis. tiap 30-60 menit) supaya tetap di bawah 2.000 menit/bulan.
2. **Yahoo Finance tidak resmi mempublikasikan rate limit**, tapi kalau terlalu banyak
   request dalam waktu singkat, Yahoo bisa menahan/menolak sementara (error/timeout). Kode ini
   sudah pakai **batch download** (1 request untuk banyak ticker) supaya lebih hemat, tapi kalau
   suatu saat sering gagal, coba kurangi frekuensi run atau jumlah ticker per run.
3. **Data delay ~15 menit**, dan kadang Yahoo Finance API berubah/eror tanpa pemberitahuan
   (ini API tidak resmi/tidak didukung kontrak SLA) — screener bisa gagal sesekali, itu wajar
   untuk sumber data gratis.
4. **Streamlit Community Cloud**: app tidur ("sleep") kalau tidak ada yang membuka selama
   12 jam berturut-turut (perlu di-klik "wake up" saat itu terjadi), resource dibatasi ±1 GB RAM,
   dan hanya 1 app Private gratis per akun (app Public tidak dibatasi jumlahnya). Update repo
   (commit baru dari GitHub Actions) dibatasi maksimal 5 kali/menit oleh Streamlit — untuk update
   tiap 15 menit ini jauh di bawah batas itu, jadi aman.
5. **GitHub Actions cron tidak presisi** — GitHub sendiri menyatakan jadwal cron bisa molor
   beberapa menit saat traffic tinggi, terutama di awal tiap jam. Jangan mengharapkan sinyal
   muncul "PAS" tiap kelipatan 15 menit.
6. **Jadwal cron tidak tahu hari libur bursa** (Thanksgiving, Natal, dll) — di hari itu workflow
   tetap jalan tapi hasilnya sama saja dengan hari sebelumnya (tidak berbahaya, cuma sedikit boros
   waktu compute).
7. **Loop 500 ticker makan waktu** — makin banyak ticker, makin lama satu run screener (dan makin
   besar juga peluang beberapa ticker gagal diambil datanya di run tsb). Workflow ini dikasih
   `timeout-minutes: 10`; kalau ternyata sering kelamaan, kurangi frekuensi update, atau pecah
   universe jadi beberapa batch di workflow terpisah.
8. **Bukan real-time & bukan alat eksekusi order** — ini murni alat bantu screening/monitoring,
   BUKAN rekomendasi investasi, dan tidak terhubung ke broker manapun.

## 8. Kalau nanti mau upgrade dari versi gratis

- Data lebih cepat & andal: langganan data provider berbayar (Polygon.io, Alpaca, dsb).
- Compute lebih fleksibel: VPS kecil (Railway/Render tier berbayar) dengan scheduler sungguhan
  (cron/APScheduler) tanpa batas menit bulanan.
- Dashboard tanpa sleep & custom domain: Streamlit tier berbayar atau hosting sendiri.
