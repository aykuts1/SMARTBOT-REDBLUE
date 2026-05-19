"""
ATR TUNNEL Bot - İndikatörler
EMA ve ATR hesaplamaları.
"""
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range hesaplaması.

    TR = MAX(
        High - Low,
        |High - Previous Close|,
        |Low - Previous Close|
    )
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range (Wilder's smoothing - alpha = 1/period)."""
    tr = true_range(df)
    # Wilder's RMA: alpha = 1/period
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
