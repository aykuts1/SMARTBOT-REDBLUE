"""
ATR TUNNEL Bot - Configuration
Hem environment variables hem config.json'dan okuma yapar.
"""
import os
import json

# ============================================================
# ENV VARIABLES (Railway'de tanımlanacak)
# ============================================================

# Mainnet API
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

# Testnet API
BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY", "")
BYBIT_TESTNET_API_SECRET = os.getenv("BYBIT_TESTNET_API_SECRET", "")

# Testnet aktif mi
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def get_api_credentials():
    """Aktif mod'a göre API key/secret döndür."""
    if BYBIT_TESTNET:
        return BYBIT_TESTNET_API_KEY, BYBIT_TESTNET_API_SECRET
    return BYBIT_API_KEY, BYBIT_API_SECRET


# ============================================================
# CONFIG.JSON (Ayarlanabilir parametreler)
# ============================================================

def load_config_json():
    """config.json dosyasını oku."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"config.json okuma hatası: {e}")
        return {}


_config = load_config_json()

# Strateji parametreleri (config.json'dan)
EMA_PERIOD = int(_config.get("ema_period", 100))
ATR_PERIOD = int(_config.get("atr_period", 14))
INNER_MULTIPLIER = float(_config.get("inner_multiplier", 2))
OUTER_MULTIPLIER = float(_config.get("outer_multiplier", 3))
TIMEFRAME = _config.get("timeframe", "5m")


# ============================================================
# SABİT PARAMETRELER
# ============================================================

# Trade ayarları
STAKE_PERCENTAGE = 0.20         # Bakiyenin %20'si stake
LEVERAGE = 50                    # 50x kaldıraç
MAX_POSITIONS = 5                # Maksimum eş zamanlı pozisyon
STOP_LOSS_PERCENT = 0.01         # %1 SL (borsa tarafında)

# Tarama
SCAN_INTERVAL_SEC = 5            # Her 5 saniyede tarama

# Emir parametreleri
ENTRY_RETRY_LIMIT = 40           # Giriş için max deneme
EXIT_RETRY_LIMIT = 40            # Çıkış için ilk faz deneme
EXIT_EXTRA_RETRY = 20            # Çıkış için ekstra deneme
ORDER_RETRY_INTERVAL_SEC = 3     # Emirler arası bekleme

# Seviye eşikleri (ATR cinsinden)
BE_TRIGGER_ATR = 0.5             # Breakeven seviyesi tetikleyici
CE_TRIGGER_ATR = 1.0             # CE takip seviyesi tetikleyici
WINRATE_TRIGGER_ATR = 5.0        # Winrate seviyesi tetikleyici

# CE takip mesafeleri (ATR cinsinden)
CE_TRAIL_ATR = 1.0               # CE Takip seviyesinde 1 ATR geriden
WINRATE_TRAIL_ATR = 0.5          # Winrate seviyesinde 0.5 ATR geriden

# Breakeven dış banda eklenen kâr oranı
BE_PROFIT_PERCENT = 0.0005       # %0.05 (işlem hacmi üzerinden)


# ============================================================
# COİN LİSTESİ
# ============================================================

SYMBOLS = [
    "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT",
    "INJUSDT", "OPUSDT", "ARBUSDT", "SUIUSDT", "TONUSDT",
    "APTUSDT", "FTMUSDT", "TIAUSDT", "ENAUSDT", "JTOUSDT",
    "XRPUSDT", "TRXUSDT", "ATOMUSDT", "ADAUSDT",
    # ALGOUSDT testnet'te mevcut değil
]


# ============================================================
# BYBIT INTERVAL EŞLEMESİ
# ============================================================

TIMEFRAME_MAP = {
    "5m":  "5",
    "15m": "15",
    "30m": "30",
    "1h":  "60",
    "2h":  "120",
    "4h":  "240",
    "1d":  "D",
}

# Timeframe'in saniye cinsinden karşılığı (kline cache için)
TIMEFRAME_SECONDS = {
    "5m":  5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h":  60 * 60,
    "2h":  120 * 60,
    "4h":  240 * 60,
    "1d":  24 * 60 * 60,
}


def get_bybit_interval():
    """config.json'daki timeframe'i Bybit interval formatına çevir."""
    return TIMEFRAME_MAP.get(TIMEFRAME, "5")


def get_timeframe_seconds():
    """Timeframe'in saniye cinsinden karşılığı."""
    return TIMEFRAME_SECONDS.get(TIMEFRAME, 300)


# ============================================================
# YENİDEN YÜKLEME
# ============================================================

def reload_config():
    """config.json'u tekrar oku - çalışma sırasında değişiklik için."""
    global _config, EMA_PERIOD, ATR_PERIOD, INNER_MULTIPLIER, OUTER_MULTIPLIER, TIMEFRAME
    _config = load_config_json()
    EMA_PERIOD = int(_config.get("ema_period", 100))
    ATR_PERIOD = int(_config.get("atr_period", 14))
    INNER_MULTIPLIER = float(_config.get("inner_multiplier", 2))
    OUTER_MULTIPLIER = float(_config.get("outer_multiplier", 3))
    TIMEFRAME = _config.get("timeframe", "5m")
