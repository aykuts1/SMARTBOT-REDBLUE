"""
ATR TUNNEL Bot - Strateji
Bant hesaplama, giriş sinyalleri, seviye geçişleri ve çıkış kontrolü.
"""
from typing import Optional, Tuple
import pandas as pd

import config
import indicators
from position_manager import Position, PositionLevel


# ============================================================
# BANT HESAPLAMA
# ============================================================

def calc_bands(df_closed: pd.DataFrame) -> dict:
    """Kapanmış mum verisinden 5 bandı hesapla.

    Args:
        df_closed: Kapanmış mumların DataFrame'i (forming candle hariç).

    Returns:
        {
            "ema":         EMA değeri,
            "atr":         ATR değeri,
            "inner_upper": EMA + ATR * iç çarpan,
            "outer_upper": EMA + ATR * dış çarpan,
            "inner_lower": EMA - ATR * iç çarpan,
            "outer_lower": EMA - ATR * dış çarpan,
        }
    """
    ema_series = indicators.ema(df_closed["close"], config.EMA_PERIOD)
    atr_series = indicators.atr(df_closed, config.ATR_PERIOD)

    ema_val = float(ema_series.iloc[-1])
    atr_val = float(atr_series.iloc[-1])

    return {
        "ema": ema_val,
        "atr": atr_val,
        "inner_upper": ema_val + atr_val * config.INNER_MULTIPLIER,
        "outer_upper": ema_val + atr_val * config.OUTER_MULTIPLIER,
        "inner_lower": ema_val - atr_val * config.INNER_MULTIPLIER,
        "outer_lower": ema_val - atr_val * config.OUTER_MULTIPLIER,
    }


# ============================================================
# GİRİŞ SİNYALİ
# ============================================================

def check_entry_signal(df_closed: pd.DataFrame, current_price: float,
                      flag_side: Optional[str]) -> Tuple[Optional[str], dict]:
    """Giriş sinyali kontrolü (her 5 saniyede).

    Args:
        df_closed: Kapanmış mumlar.
        current_price: Anlık fiyat.
        flag_side: Mevcut flag yönü ("long", "short" veya None).

    Returns:
        (action, bands) -> action:
            "long_direct"   : Direkt long girişi
            "long_flag"     : Long flag aç
            "long_enter"    : Mevcut long flag tetiklendi, gir
            "long_cancel"   : Long flag iptal
            "short_direct"  : Direkt short girişi
            "short_flag"    : Short flag aç
            "short_enter"   : Mevcut short flag tetiklendi, gir
            "short_cancel"  : Short flag iptal
            None            : Bir şey yok
    """
    bands = calc_bands(df_closed)
    last_close = float(df_closed["close"].iloc[-1])

    # ----- Mevcut LONG flag kontrolü -----
    if flag_side == "long":
        if current_price > bands["outer_upper"]:
            return ("long_enter", bands)
        if current_price < bands["inner_upper"]:
            return ("long_cancel", bands)
        return (None, bands)  # Flag korunuyor

    # ----- Mevcut SHORT flag kontrolü -----
    if flag_side == "short":
        if current_price < bands["outer_lower"]:
            return ("short_enter", bands)
        if current_price > bands["inner_lower"]:
            return ("short_cancel", bands)
        return (None, bands)

    # ----- Flag yok, yeni sinyal kontrolü -----
    # LONG: son mum iç bandın üstünde kapandı mı?
    if last_close > bands["inner_upper"]:
        if current_price > bands["outer_upper"]:
            return ("long_direct", bands)
        return ("long_flag", bands)

    # SHORT: son mum iç bandın altında kapandı mı?
    if last_close < bands["inner_lower"]:
        if current_price < bands["outer_lower"]:
            return ("short_direct", bands)
        return ("short_flag", bands)

    return (None, bands)


# ============================================================
# SEVİYE GÜNCELLEME
# ============================================================

def update_position_levels(pos: Position, current_price: float,
                          bands: dict) -> Optional[str]:
    """Pozisyonun seviyesini güncelle.

    Returns:
        Seviye değişimi olduysa: "level_up_be" / "level_up_ce" / "level_up_winrate"
        Yoksa None
    """
    entry_atr = pos.entry_atr

    if pos.side == "long":
        # Best price güncelle (long için en yüksek)
        if current_price > pos.best_price:
            pos.best_price = current_price

        profit_in_atr = (current_price - pos.entry_price) / entry_atr if entry_atr > 0 else 0

        # Mevcut seviyeye göre dinamik güncellemeler
        if pos.level in (PositionLevel.BREAKEVEN, PositionLevel.CE_TRAIL, PositionLevel.WINRATE):
            # BE seviyesi dış bantla birlikte hareket eder (yukarı/aşağı)
            pos.be_level = bands["outer_upper"] * (1 + config.BE_PROFIT_PERCENT)

        if pos.level == PositionLevel.CE_TRAIL:
            # CE seviyesi en iyi fiyat - 1 ATR (sadece lehe hareket)
            new_ce = pos.best_price - entry_atr * config.CE_TRAIL_ATR
            if new_ce > pos.ce_level:
                pos.ce_level = new_ce

        if pos.level == PositionLevel.WINRATE:
            # CE seviyesi sıkıştırılmış (0.5 ATR)
            new_ce = pos.best_price - entry_atr * config.WINRATE_TRAIL_ATR
            if new_ce > pos.ce_level:
                pos.ce_level = new_ce

        # Seviye yükseltme kontrolü
        if pos.level == PositionLevel.ENTRY and profit_in_atr >= config.BE_TRIGGER_ATR:
            pos.level = PositionLevel.BREAKEVEN
            pos.be_level = bands["outer_upper"] * (1 + config.BE_PROFIT_PERCENT)
            return "level_up_be"

        if pos.level == PositionLevel.BREAKEVEN and profit_in_atr >= config.CE_TRIGGER_ATR:
            pos.level = PositionLevel.CE_TRAIL
            pos.ce_level = pos.best_price - entry_atr * config.CE_TRAIL_ATR
            return "level_up_ce"

        if pos.level == PositionLevel.CE_TRAIL and profit_in_atr >= config.WINRATE_TRIGGER_ATR:
            pos.level = PositionLevel.WINRATE
            pos.ce_level = pos.best_price - entry_atr * config.WINRATE_TRAIL_ATR
            return "level_up_winrate"

    else:  # short
        # Best price güncelle (short için en düşük)
        if pos.best_price == 0 or current_price < pos.best_price:
            pos.best_price = current_price

        profit_in_atr = (pos.entry_price - current_price) / entry_atr if entry_atr > 0 else 0

        # Dinamik güncellemeler
        if pos.level in (PositionLevel.BREAKEVEN, PositionLevel.CE_TRAIL, PositionLevel.WINRATE):
            pos.be_level = bands["outer_lower"] * (1 - config.BE_PROFIT_PERCENT)

        if pos.level == PositionLevel.CE_TRAIL:
            new_ce = pos.best_price + entry_atr * config.CE_TRAIL_ATR
            if pos.ce_level == 0 or new_ce < pos.ce_level:
                pos.ce_level = new_ce

        if pos.level == PositionLevel.WINRATE:
            new_ce = pos.best_price + entry_atr * config.WINRATE_TRAIL_ATR
            if pos.ce_level == 0 or new_ce < pos.ce_level:
                pos.ce_level = new_ce

        # Seviye yükseltme
        if pos.level == PositionLevel.ENTRY and profit_in_atr >= config.BE_TRIGGER_ATR:
            pos.level = PositionLevel.BREAKEVEN
            pos.be_level = bands["outer_lower"] * (1 - config.BE_PROFIT_PERCENT)
            return "level_up_be"

        if pos.level == PositionLevel.BREAKEVEN and profit_in_atr >= config.CE_TRIGGER_ATR:
            pos.level = PositionLevel.CE_TRAIL
            pos.ce_level = pos.best_price + entry_atr * config.CE_TRAIL_ATR
            return "level_up_ce"

        if pos.level == PositionLevel.CE_TRAIL and profit_in_atr >= config.WINRATE_TRIGGER_ATR:
            pos.level = PositionLevel.WINRATE
            pos.ce_level = pos.best_price + entry_atr * config.WINRATE_TRAIL_ATR
            return "level_up_winrate"

    return None


# ============================================================
# ÇIKIŞ KONTROLÜ
# ============================================================

def check_exit_conditions(pos: Position, current_price: float,
                          bands: dict) -> Optional[str]:
    """Çıkış koşullarını kontrol et.

    Her seviyede önceki seviyelerin çıkışları da geçerli (birikimli).

    Returns:
        Çıkış sebebi:
            "outer_band_exit"  - dış bant içine giriş
            "breakeven_exit"   - BE seviyesi altı/üstü
            "ce_exit"          - CE seviyesine çarpma
            "winrate_exit"     - Winrate CE'sine çarpma
        Veya None (çıkış yok)
    """
    if pos.side == "long":
        # En öncelikli: en sıkı kontrol
        # Winrate / CE Trail: CE çarpması
        if pos.level == PositionLevel.WINRATE:
            if current_price <= pos.ce_level:
                return "winrate_exit"
        elif pos.level == PositionLevel.CE_TRAIL:
            if current_price <= pos.ce_level:
                return "ce_exit"

        # BE: BE altına düştü mü? (CE seviyesindeyken de geçerli, ama
        # CE zaten BE'den yukarıda olduğu için pratikte CE önce tetiklenir)
        if pos.level in (PositionLevel.BREAKEVEN, PositionLevel.CE_TRAIL, PositionLevel.WINRATE):
            if current_price <= pos.be_level:
                return "breakeven_exit"

        # Her zaman: dış bant içine giriş
        if current_price <= bands["outer_upper"]:
            return "outer_band_exit"

    else:  # short
        if pos.level == PositionLevel.WINRATE:
            if current_price >= pos.ce_level:
                return "winrate_exit"
        elif pos.level == PositionLevel.CE_TRAIL:
            if current_price >= pos.ce_level:
                return "ce_exit"

        if pos.level in (PositionLevel.BREAKEVEN, PositionLevel.CE_TRAIL, PositionLevel.WINRATE):
            if current_price >= pos.be_level:
                return "breakeven_exit"

        if current_price >= bands["outer_lower"]:
            return "outer_band_exit"

    return None


# ============================================================
# YARDIMCI HESAPLAR
# ============================================================

def calc_profit_metrics(pos: Position, price: float) -> dict:
    """Bir fiyat için kâr metrikleri hesapla."""
    if pos.side == "long":
        diff = price - pos.entry_price
    else:
        diff = pos.entry_price - price

    pct = (diff / pos.entry_price) * 100 if pos.entry_price > 0 else 0
    atr_units = diff / pos.entry_atr if pos.entry_atr > 0 else 0
    # PNL = (fiyat farkı / giriş fiyatı) * pozisyon büyüklüğü
    pnl = (diff / pos.entry_price) * pos.position_size if pos.entry_price > 0 else 0

    return {
        "pct": pct,
        "atr": atr_units,
        "pnl": pnl,
    }
