"""
Teknik göstergeler: EMA, RSI, ATR, Chandelier Exit ve yardımcılar.
Tamamı pandas/numpy ile, harici ta-lib gerektirmez.
"""
from __future__ import annotations

from typing import Tuple, Optional
import numpy as np
import pandas as pd


# ============= EMA =============
def ema(series: pd.Series, period: int) -> pd.Series:
    """Üstel hareketli ortalama (TradingView ile uyumlu)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


# ============= RSI (Wilder) =============
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI - TradingView'in default RSI'ı ile uyumlu."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # Wilder smoothing: alpha = 1/period
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_values = 100 - (100 / (1 + rs))
    # avg_loss 0 ise RSI 100 olur
    rsi_values = rsi_values.fillna(100)
    return rsi_values


# ============= ATR (Wilder) =============
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ATR."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# ============= Dinamik RSI Eşikleri =============
def dynamic_rsi_thresholds(
    rsi_series: pd.Series,
    lookback: int = 100,
    extreme_count: int = 10,
) -> Tuple[float, float]:
    """
    Son `lookback` RSI değerinin en düşük `extreme_count` tanesinin ortalaması = long eşiği.
    En yüksek `extreme_count` tanesinin ortalaması = short eşiği.
    """
    clean = rsi_series.dropna()
    if len(clean) < lookback:
        # Yeterli veri yoksa muhafazakar varsayılan değerler
        return 30.0, 70.0

    window = clean.iloc[-lookback:].values
    sorted_vals = np.sort(window)
    long_th = float(sorted_vals[:extreme_count].mean())
    short_th = float(sorted_vals[-extreme_count:].mean())
    return long_th, short_th


# ============= ATR Oranı =============
def atr_ratio(atr_series: pd.Series, lookback: int = 100) -> float:
    """
    Son kapanan ATR / son `lookback` ATR'nin ortalaması.
    """
    clean = atr_series.dropna()
    if len(clean) < lookback:
        return 0.0

    current = float(clean.iloc[-1])
    avg = float(clean.iloc[-lookback:].mean())
    if avg <= 0:
        return 0.0
    return current / avg


# ============= Chandelier Exit =============
def chandelier_exit_long(
    high: pd.Series,
    atr_series: pd.Series,
    period: int,
    multiplier: float,
    lookback_end: Optional[int] = None,
) -> float:
    """
    Long pozisyon için CE: son `period` mumun en yükseği - multiplier * ATR.
    `lookback_end` verilirse o indekse kadar (dahil) hesaplanır, verilmezse son değer.
    """
    if lookback_end is None:
        h_window = high.iloc[-period:]
        a_val = float(atr_series.iloc[-1])
    else:
        end = lookback_end + 1
        start = max(0, end - period)
        h_window = high.iloc[start:end]
        a_val = float(atr_series.iloc[lookback_end])
    return float(h_window.max()) - multiplier * a_val


def chandelier_exit_short(
    low: pd.Series,
    atr_series: pd.Series,
    period: int,
    multiplier: float,
    lookback_end: Optional[int] = None,
) -> float:
    """
    Short pozisyon için CE: son `period` mumun en düşüğü + multiplier * ATR.
    """
    if lookback_end is None:
        l_window = low.iloc[-period:]
        a_val = float(atr_series.iloc[-1])
    else:
        end = lookback_end + 1
        start = max(0, end - period)
        l_window = low.iloc[start:end]
        a_val = float(atr_series.iloc[lookback_end])
    return float(l_window.min()) + multiplier * a_val


# ============= RSI Crossover =============
def rsi_cross_up(rsi_series: pd.Series, threshold: float) -> bool:
    """
    Önceki kapanış altında, son kapanış üstünde/eşit → yukarı cross.
    """
    clean = rsi_series.dropna()
    if len(clean) < 2:
        return False
    prev = float(clean.iloc[-2])
    last = float(clean.iloc[-1])
    return prev < threshold <= last


def rsi_cross_down(rsi_series: pd.Series, threshold: float) -> bool:
    """
    Önceki kapanış üstünde, son kapanış altında/eşit → aşağı cross.
    """
    clean = rsi_series.dropna()
    if len(clean) < 2:
        return False
    prev = float(clean.iloc[-2])
    last = float(clean.iloc[-1])
    return prev > threshold >= last
