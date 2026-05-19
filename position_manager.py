"""
ATR TUNNEL Bot - Position Manager
Pozisyonlar, flag'ler, trade geçmişi ve sağlık durumu state'i tutar.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import config


# ============================================================
# ENUM'LAR
# ============================================================

class PositionLevel(Enum):
    """İşlem seviyeleri."""
    ENTRY = 1
    BREAKEVEN = 2
    CE_TRAIL = 3
    WINRATE = 4

    @property
    def label(self) -> str:
        labels = {
            PositionLevel.ENTRY: "Giriş",
            PositionLevel.BREAKEVEN: "Breakeven",
            PositionLevel.CE_TRAIL: "CE Takip",
            PositionLevel.WINRATE: "Winrate",
        }
        return labels[self]


# ============================================================
# DATA CLASSLARI
# ============================================================

@dataclass
class Position:
    """Açık bir pozisyonu temsil eder."""
    symbol: str
    side: str                # "long" veya "short"
    entry_price: float
    entry_atr: float
    quantity: float          # Coin miktarı
    position_size: float     # USDT cinsinden (stake × leverage)
    stake: float             # USDT cinsinden teminat
    open_time: datetime = field(default_factory=datetime.now)
    level: PositionLevel = PositionLevel.ENTRY
    best_price: float = 0.0
    be_level: float = 0.0
    ce_level: float = 0.0
    sl_price: float = 0.0


@dataclass
class Flag:
    """Bir flag (sinyal beklemede)."""
    symbol: str
    side: str                # "long" veya "short"
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TradeRecord:
    """Tamamlanmış bir işlemin kaydı (rapor için)."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    position_size: float
    stake: float
    entry_atr: float
    pnl: float               # USDT
    pnl_pct: float           # %
    pnl_atr: float           # ATR cinsinden
    open_time: datetime
    close_time: datetime
    exit_type: str           # "outer_band", "breakeven", "ce_trail", "winrate", "stoploss"
    max_level: PositionLevel

    @property
    def is_profit(self) -> bool:
        return self.pnl > 0


@dataclass
class FailedSignal:
    """Açılamayan sinyal kaydı."""
    symbol: str
    side: str
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================
# STATE MANAGER
# ============================================================

class StateManager:
    """Botun tüm runtime state'ini tutar."""

    def __init__(self):
        # Aktif pozisyonlar (symbol -> Position)
        self.positions: dict[str, Position] = {}

        # Aktif flag'ler (symbol -> Flag)
        self.flags: dict[str, Flag] = {}

        # Trade geçmişi (kapanan işlemler)
        self.trades: list[TradeRecord] = []

        # Açılamayan sinyaller
        self.failed_signals: list[FailedSignal] = []

        # Sabit stake (bot başlangıcında belirlenir, restart'a kadar değişmez)
        self.locked_stake: float = 0.0

        # Başlangıç bakiye
        self.start_balance: float = 0.0

        # Bot başlangıç zamanı
        self.start_time: datetime = datetime.now()

        # İşlem in-progress (entry/exit attempting)
        self.busy_symbols: set[str] = set()

    # ---------- Pozisyon yönetimi ----------

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def position_count(self) -> int:
        return len(self.positions)

    def can_open_new_position(self) -> bool:
        return len(self.positions) < config.MAX_POSITIONS

    def add_position(self, pos: Position) -> None:
        self.positions[pos.symbol] = pos

    def remove_position(self, symbol: str) -> None:
        if symbol in self.positions:
            del self.positions[symbol]

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    # ---------- Flag yönetimi ----------

    def get_flag_side(self, symbol: str) -> Optional[str]:
        flag = self.flags.get(symbol)
        return flag.side if flag else None

    def set_flag(self, symbol: str, side: str) -> None:
        self.flags[symbol] = Flag(symbol=symbol, side=side)

    def clear_flag(self, symbol: str) -> None:
        if symbol in self.flags:
            del self.flags[symbol]

    # ---------- Trade kayıt ----------

    def add_trade(self, trade: TradeRecord) -> None:
        self.trades.append(trade)

    def add_failed_signal(self, symbol: str, side: str, reason: str) -> None:
        self.failed_signals.append(FailedSignal(
            symbol=symbol, side=side, reason=reason
        ))

    # ---------- Busy state ----------

    def mark_busy(self, symbol: str) -> None:
        self.busy_symbols.add(symbol)

    def mark_free(self, symbol: str) -> None:
        self.busy_symbols.discard(symbol)

    def is_busy(self, symbol: str) -> bool:
        return symbol in self.busy_symbols
