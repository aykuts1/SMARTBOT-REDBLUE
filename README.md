# ATR TUNNEL Bot

Bybit USDT perpetual üzerinde EMA + ATR tabanlı çift bant stratejisi ile otomatik scalp yapan bot.

## Strateji

Beş çizgili bant:

```
Üst dış bant  = EMA + ATR × outer_multiplier  (varsayılan 3)
Üst iç bant   = EMA + ATR × inner_multiplier  (varsayılan 2)
Orta          = EMA                            (varsayılan 100)
Alt iç bant   = EMA - ATR × inner_multiplier
Alt dış bant  = EMA - ATR × outer_multiplier
```

### Giriş

Her 5 saniyede tarama:

1. Son kapanmış mum iç bandın dışında mı?
2. Evet ise:
   - Anlık fiyat dış bandı geçtiyse → direkt giriş
   - Geçmediyse → flag açılır
3. Flagli coinler:
   - Anlık fiyat dış bandı geçti → giriş
   - Anlık fiyat iç bandın içine döndü → flag iptal

### İşlem Seviyeleri (Çıkış birikimli)

| Seviye | Tetik | Çıkış Koşulu |
|---|---|---|
| Giriş | açılış | Fiyat dış bant içine girer |
| Breakeven | +0.5 ATR | BE = dış bant × 1.0005 (dinamik) |
| CE Takip | +1 ATR | En iyi fiyat - 1 ATR'a çarpma |
| Winrate | +5 ATR | CE 0.5 ATR'a sıkışır |

Her seviyede önceki seviyelerin çıkışları da geçerli.

### Stoploss

%1 sabit SL borsa tarafında (emniyet kemeri).

## Konfigürasyon

`config.json` — strateji parametreleri çalışma sırasında değiştirilebilir.
Yeni mum kapanışından sonra yeniden okunur (botu yeniden başlatmaya gerek yok).

```json
{
  "ema_period": 100,
  "atr_period": 14,
  "inner_multiplier": 2,
  "outer_multiplier": 3,
  "timeframe": "5m"
}
```

Geçerli timeframe değerleri: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`.

## Environment Variables (Railway)

| Değişken | Zorunlu | Açıklama |
|---|---|---|
| `BYBIT_TESTNET_API_KEY` | Testnet kullanılırken | Testnet API key |
| `BYBIT_TESTNET_API_SECRET` | Testnet kullanılırken | Testnet API secret |
| `BYBIT_API_KEY` | Mainnet kullanılırken | Mainnet API key |
| `BYBIT_API_SECRET` | Mainnet kullanılırken | Mainnet API secret |
| `BYBIT_TESTNET` | Hayır | `true` ise testnet (varsayılan), `false` ise mainnet |
| `TELEGRAM_BOT_TOKEN` | Evet | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Evet | Telegram chat ID |

## Trade Ayarları

- 20 coin: SOL, AVAX, LINK, DOT, NEAR, INJ, OP, ARB, SUI, TON, APT, FTM, TIA, ENA, JTO, XRP, TRX, ATOM, ADA, ALGO
- Stake: Bakiyenin %20'si (bot başlangıcında sabitlenir)
- Kaldıraç: 50x isolated
- Max 5 eş zamanlı pozisyon
- Aynı coinde max 1 pozisyon
- Limit post-only emirler, market kullanılmaz (sadece çıkışta son çare olarak)
- Giriş: 40 deneme (3sn aralık), dolmazsa sinyal atlanır
- Çıkış: 40 + 20 limit deneme, sonra market

## Telegram Bildirimleri

- 🚀 Bot başlangıcı
- 🟢 İşlem açıldı
- 🎯 Breakeven aktif
- 📈 CE Takip aktif
- 🚀 Winrate aktif
- 🔴 İşlem kapandı
- 🛑 Stoploss tetiklendi
- ⚠️ Sinyal açılamadı
- 🔧 Market kapatış (son çare)
- 📊 Saatlik rapor
- 📊 12 saatlik rapor (00:00 ve 12:00)
- 📋 Günlük Z raporu (09:00)
- ⚠️ API bağlantı durumu

## Dosya Yapısı

```
scalp-bot/
├── main.py              # Ana döngü, scheduler
├── config.py            # ENV + config.json okuma
├── config.json          # Ayarlanabilir parametreler
├── indicators.py        # EMA, ATR
├── strategy.py          # Bant, sinyal, seviye, çıkış
├── position_manager.py  # State yönetimi
├── bybit_client.py      # Bybit API wrapper
├── telegram_bot.py      # Telegram bildirimleri ve raporlar
├── requirements.txt
├── Procfile             # Railway worker
├── runtime.txt
└── README.md
```

## Bybit API İzinleri

API key'in şu izinlere sahip olması gerekir:

- ✅ Contract / Unified Trading: Orders + Positions
- ❌ Withdraw (kapalı kalsın)

## Risk Uyarısı

Bu bot finansal tavsiye değildir. Kripto vadeli işlemler yüksek risklidir, sermayenizin tamamını kaybedebilirsiniz. Önce testnet'te ve düşük tutarlarla test edin.
