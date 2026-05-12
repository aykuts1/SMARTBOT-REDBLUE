# Bybit Futures Scalp Bot

Bybit USDT perpetual futures üzerinde 30 dakikalık zaman diliminde RSI crossover + EMA200 + ATR filtresi ile scalping yapan otomatik bot. Railway worker olarak çalışmak üzere tasarlanmıştır.

## Strateji Özeti

**Göstergeler**
- EMA 200 (30dk ve 2 saat)
- RSI 14 (30dk)
- ATR 14 (30dk)
- Chandelier Exit (22 mum, 1 ATR geride)

**Dinamik RSI Eşikleri**
Son 100 RSI değerinin en düşük 10'unun ortalaması = long eşiği; en yüksek 10'unun ortalaması = short eşiği. Her mum kapanışında yeniden hesaplanır.

**ATR Filtresi**
Anlık ATR / son 100 mumun ATR ortalaması < 0.8 ise işlem açılmaz.

**Long Sinyal**
- RSI dinamik long eşiğinin altına düşüp geri yukarı çıkar (önceki mum < eşik, son mum ≥ eşik)
- Fiyat 30dk EMA200 üstünde
- Fiyat 2H EMA200 üstünde
- ATR oranı ≥ 0.8
- Mum kapanışıyla giriş

**Short Sinyal**
Long'un tam tersi.

**Pozisyon Yönetimi**
- Bot başlangıcında bakiyenin %20'si stake olarak kilitlenir (restart'a kadar sabit)
- 10x kaldıraç
- Maksimum 5 eş zamanlı açık pozisyon
- Aynı coinde maksimum 1 açık pozisyon

**Stop ve Kâr Yönetimi**
- Giriş: %1 sabit stop (Bybit pozisyon seviyesinde) + 1 ATR geride Chandelier Exit (bot tarafında)
- 0.5 ATR kârda stop entry + 0.2 ATR seviyesine taşınır (BE)
- 1 ATR kârda CE 0.5 ATR geride takibe geçer
- Hangisi önce tetiklenirse pozisyon kapanır

**Emir Tipi**
Limit emir, market gibi dolması için fiyatın %0.05 ötesinde verilir.

## Dosya Yapısı

```
.
├── config.py              # Environment variables ve sabitler
├── bybit_client.py        # Bybit v5 API wrapper
├── indicators.py          # EMA, RSI, ATR, Chandelier Exit
├── strategy.py            # Sinyal üretimi ve filtreler
├── position_manager.py    # Pozisyon hafızası ve yönetimi
├── telegram_bot.py        # Telegram bildirimleri
├── main.py                # Ana giriş + scheduler
├── requirements.txt       # Python bağımlılıkları
├── Procfile               # Railway worker komutu
├── runtime.txt            # Python sürümü
└── README.md
```

## Environment Variables

Railway'de aşağıdaki değişkenleri ayarlamak gerekir:

| Değişken | Zorunlu | Açıklama |
|----------|---------|----------|
| `BYBIT_API_KEY` | ✅ | Bybit API anahtarı |
| `BYBIT_API_SECRET` | ✅ | Bybit API gizli anahtarı |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram bot token (BotFather'dan) |
| `TELEGRAM_CHAT_ID` | ✅ | Telegram chat ID (mesajların gönderileceği) |
| `SYMBOLS` | ❌ | Virgülle ayrılmış sembol listesi (boşsa varsayılan kullanılır) |
| `BYBIT_TESTNET` | ❌ | `true` ise testnet kullanır (varsayılan: `false`) |

## Varsayılan Sembol Listesi

BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, SUIUSDT, ZECUSDT, DOGEUSDT, TONUSDT, TRXUSDT, AAVEUSDT, ADAUSDT, LTCUSDT, LINKUSDT, APTUSDT, INJUSDT, AVAXUSDT, NEARUSDT, 1000PEPEUSDT, MEGAUSDT, ONDOUSDT, HYPEUSDT, UNIUSDT, ASTERUSDT, WLDUSDT, OPUSDT, ARBUSDT, STXUSDT, JUPUSDT, ENAUSDT, TIAUSDT, FETUSDT, SEIUSDT, EIGENUSDT

## Bybit API İzinleri

Oluşturacağın API key'in şu izinlere sahip olması gerekir:
- ✅ **Contract / Unified Trading**: Orders + Positions
- ❌ Withdraw (kapalı kalsın)

## Railway'de Kurulum

1. Bu repoyu GitHub'a push et
2. Railway'de yeni proje → "Deploy from GitHub repo"
3. Repoyu seç
4. Settings → Variables sekmesinden environment variables'ları ekle
5. Deploy başlayacak; logları takip et

Procfile sayesinde Railway otomatik olarak `worker: python main.py` komutunu çalıştırır.

## Lokal Test

```bash
# Python 3.11.6 önerilir
pip install -r requirements.txt

# .env dosyası oluştur
cat > .env <<EOF
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
BYBIT_TESTNET=true
EOF

# Test için python-dotenv yükle ve main.py'a şu satırı ekle (üst kısma):
# from dotenv import load_dotenv; load_dotenv()

python main.py
```

## Telegram Bildirimleri

Bot şu durumlarda Telegram mesajı gönderir:

- 🚀 Bot başlangıcında: bakiye, stake, kaldıraç, sembol sayısı
- 🟢/🔴 Pozisyon açılışında: coin, yön, fiyat, miktar, stop, CE, stake
- ✅/❌ Pozisyon kapanışında: çıkış fiyatı, sebep (SL/CE), PnL ($ ve %)
- ⚠️ Crossover var ama filtreye takıldıysa: hangi filtreye takıldığı
- 🚫 5 pozisyon dolu ve sinyal geldiyse
- 🔁 Aynı coinde pozisyon varken sinyal geldiyse
- 📊 Her 30dk tarama sonunda özet
- 🚨 API/bağlantı hatası

## Önemli Notlar

- **Bot Unified Trading hesabı kullanır**. Klasik hesap (eski tip) için `bybit_client.py`'da `ACCOUNT_TYPE = "CONTRACT"` olarak değiştirilebilir.
- **Pozisyon modu**: One-way mode varsayılır (positionIdx=0). Hedge mode kullanıyorsan değiştir.
- **Stake bot başlangıcında sabitlenir**. Bakiye değişse de stake değişmez. Stake'i güncellemek için botu restart et.
- **CE seviyesi sadece bot hafızasında tutulur** (Bybit'te değil). Bot restart olursa açık pozisyonların CE state'i kaybolur ama Bybit'teki %1 stop korunur. Restart sonrası CE seviyeleri yeniden hesaplanmaz; manuel müdahale gerekir.
- **API rate limit**: Bot her 30dk'da 34 sembol × 2 timeframe = 68 kline çağrısı yapar; Bybit limitleri içinde rahat çalışır.

## Risk Uyarısı

Bu bot finansal tavsiye değildir. Kripto vadeli işlemler yüksek risklidir, sermayenizin tamamını kaybedebilirsiniz. Önce testnet'te ve düşük tutarlarla test edin. Yazılım hataları, ağ kesintileri, borsa kesintileri vb. nedenlerle beklenmedik kayıplar oluşabilir. Kullanım kendi sorumluluğunuzdadır.
