"""
ATR TUNNEL Bot - Telegram Bildirimleri
İşlem bildirimleri, seviye değişimleri ve raporlar.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import requests

import config
from position_manager import (
    Position, StateManager, TradeRecord
)

logger = logging.getLogger(__name__)


# ============================================================
# ÇIKIŞ TİPLERİ — KULLANICI DOSTU İSİMLER
# ============================================================

EXIT_TYPE_LABELS = {
    "outer_band_exit": "Dış Bant Çıkışı",
    "breakeven_exit":  "Breakeven Çıkışı",
    "ce_exit":         "CE Takip Çıkışı",
    "winrate_exit":    "Winrate Çıkışı",
    "stoploss":        "Stoploss",
}

FAIL_REASON_LABELS = {
    "slot_full":         "Slot dolu",
    "already_open":      "Aynı coinde pozisyon var",
    "retry_exhausted":   "40 deneme doldu",
    "insufficient_qty":  "Yetersiz miktar (min qty altı)",
    "api_error":         "API hatası",
}


# ============================================================
# TELEGRAM CLIENT
# ============================================================

class TelegramBot:
    """Telegram bot wrapper."""

    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram token/chat_id yok, mesaj atlanıyor")
            return False
        try:
            # Mesaj çok uzunsa böl
            if len(text) > 4000:
                parts = self._split_long(text, 4000)
                ok = True
                for p in parts:
                    if not self._send_one(p):
                        ok = False
                return ok
            return self._send_one(text)
        except Exception as e:
            logger.error(f"Telegram gönderme hatası: {e}")
            return False

    def _send_one(self, text: str) -> bool:
        try:
            r = requests.post(
                self.url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Telegram POST hatası: {e}")
            return False

    @staticmethod
    def _split_long(text: str, max_len: int) -> list[str]:
        parts = []
        lines = text.split("\n")
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > max_len:
                parts.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            parts.append(current)
        return parts

    @staticmethod
    def _now_str() -> str:
        return datetime.now().strftime("%H:%M | %d.%m.%Y")


# ============================================================
# YARDIMCI FORMATTER'LAR
# ============================================================

def _fmt_price(p: float) -> str:
    """Fiyatı uygun precision'da formatla."""
    if p == 0:
        return "0"
    if abs(p) >= 1000:
        return f"{p:.2f}"
    if abs(p) >= 1:
        return f"{p:.4f}"
    if abs(p) >= 0.01:
        return f"{p:.5f}"
    return f"{p:.7f}"


def _fmt_pnl(pnl: float) -> str:
    return f"{pnl:+.2f}"


def _fmt_pct(pct: float) -> str:
    return f"{pct:+.2f}%"


def _fmt_atr(atr_units: float) -> str:
    return f"{atr_units:+.1f} ATR"


# ============================================================
# OLAY BAZLI BİLDİRİMLER
# ============================================================

def notify_bot_started(tg: TelegramBot, balance: float, stake: float,
                       active_mode: str) -> None:
    text = (
        f"🚀 ATR TUNNEL BAŞLADI — {tg._now_str()}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Mod: {active_mode}\n"
        f"Bakiye: {balance:.2f} USDT\n"
        f"Stake: {stake:.2f} USDT ({int(config.STAKE_PERCENTAGE*100)}%)\n"
        f"Kaldıraç: {config.LEVERAGE}x isolated\n"
        f"Max Pozisyon: {config.MAX_POSITIONS}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Timeframe: {config.TIMEFRAME}\n"
        f"EMA: {config.EMA_PERIOD} | ATR: {config.ATR_PERIOD}\n"
        f"İç Bant: ×{config.INNER_MULTIPLIER} | Dış: ×{config.OUTER_MULTIPLIER}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Coin sayısı: {len(config.SYMBOLS)}"
    )
    tg.send(text)


def notify_trade_opened(tg: TelegramBot, pos: Position) -> None:
    side_label = "Long" if pos.side == "long" else "Short"
    text = (
        f"🟢 İŞLEM AÇILDI — {tg._now_str()}\n\n"
        f"┌─ {pos.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(pos.entry_price)}\n"
        f"│ Stake: {pos.stake:.2f} USDT\n"
        f"│ Kaldıraç: {config.LEVERAGE}x\n"
        f"│ SL: {_fmt_price(pos.sl_price)}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_breakeven_active(tg: TelegramBot, pos: Position, current_price: float,
                            metrics: dict) -> None:
    side_label = "Long" if pos.side == "long" else "Short"
    text = (
        f"🎯 BREAKEVEN AKTİF — {tg._now_str()}\n\n"
        f"┌─ {pos.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(pos.entry_price)}\n"
        f"│ Şu an: {_fmt_price(current_price)} "
        f"({_fmt_pct(metrics['pct'])} | {_fmt_atr(metrics['atr'])})\n"
        f"│ BE Seviyesi: {_fmt_price(pos.be_level)}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_ce_trail_active(tg: TelegramBot, pos: Position, current_price: float,
                           metrics: dict) -> None:
    side_label = "Long" if pos.side == "long" else "Short"
    text = (
        f"📈 CE TAKİP AKTİF — {tg._now_str()}\n\n"
        f"┌─ {pos.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(pos.entry_price)}\n"
        f"│ Şu an: {_fmt_price(current_price)} "
        f"({_fmt_pct(metrics['pct'])} | {_fmt_atr(metrics['atr'])})\n"
        f"│ CE Seviyesi: {_fmt_price(pos.ce_level)}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_winrate_active(tg: TelegramBot, pos: Position, current_price: float,
                          metrics: dict) -> None:
    side_label = "Long" if pos.side == "long" else "Short"
    text = (
        f"🚀 WİNRATE AKTİF — {tg._now_str()}\n\n"
        f"┌─ {pos.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(pos.entry_price)}\n"
        f"│ Şu an: {_fmt_price(current_price)} "
        f"({_fmt_pct(metrics['pct'])} | {_fmt_atr(metrics['atr'])})\n"
        f"│ CE Seviyesi: {_fmt_price(pos.ce_level)}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_trade_closed(tg: TelegramBot, trade: TradeRecord) -> None:
    side_label = "Long" if trade.side == "long" else "Short"
    icon = "🟢" if trade.is_profit else "🔴"
    word = "Kar" if trade.is_profit else "Zarar"
    exit_label = EXIT_TYPE_LABELS.get(trade.exit_type, trade.exit_type)
    text = (
        f"{icon} İŞLEM KAPANDI — {tg._now_str()}\n\n"
        f"┌─ {trade.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(trade.entry_price)}\n"
        f"│ Çıkış: {_fmt_price(trade.exit_price)}\n"
        f"│ {word}: {_fmt_pct(trade.pnl_pct)} | {_fmt_atr(trade.pnl_atr)}\n"
        f"│ PNL: {_fmt_pnl(trade.pnl)} USDT\n"
        f"│ Çıkış Tipi: {exit_label}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_stoploss(tg: TelegramBot, trade: TradeRecord) -> None:
    side_label = "Long" if trade.side == "long" else "Short"
    text = (
        f"🛑 STOPLOSS TETİKLENDİ — {tg._now_str()}\n\n"
        f"┌─ {trade.symbol} — {side_label} ─────────\n"
        f"│ Giriş: {_fmt_price(trade.entry_price)}\n"
        f"│ Çıkış: {_fmt_price(trade.exit_price)}\n"
        f"│ Zarar: {_fmt_pct(trade.pnl_pct)} | {_fmt_atr(trade.pnl_atr)}\n"
        f"│ PNL: {_fmt_pnl(trade.pnl)} USDT\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_signal_failed(tg: TelegramBot, symbol: str, side: str,
                        reason: str) -> None:
    side_label = "Long" if side == "long" else "Short"
    reason_label = FAIL_REASON_LABELS.get(reason, reason)
    text = (
        f"⚠️ SİNYAL AÇILAMADI — {tg._now_str()}\n\n"
        f"┌─ {symbol} — {side_label} ─────────\n"
        f"│ Sebep: {reason_label}\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_market_close(tg: TelegramBot, symbol: str, side: str) -> None:
    side_label = "Long" if side == "long" else "Short"
    text = (
        f"🔧 MARKET KAPATIŞ — {tg._now_str()}\n\n"
        f"┌─ {symbol} — {side_label} ─────────\n"
        f"│ 60 limit denemesi doldu\n"
        f"│ Market emirle kapatıldı (taker)\n"
        f"└──────────────────────"
    )
    tg.send(text)


def notify_api_lost(tg: TelegramBot) -> None:
    tg.send(
        f"⚠️ API BAĞLANTISI KESİLDİ — {tg._now_str()}\n"
        f"Yeniden bağlanılıyor..."
    )


def notify_api_restored(tg: TelegramBot) -> None:
    tg.send(
        f"✅ BAĞLANTI SAĞLANDI — {tg._now_str()}\n"
        f"Bot çalışmaya devam ediyor."
    )


# ============================================================
# RAPORLAR
# ============================================================

def _filter_trades(trades: list[TradeRecord], window: timedelta) -> list[TradeRecord]:
    cutoff = datetime.now() - window
    return [t for t in trades if t.close_time >= cutoff]


def _filter_failed(failed: list, window: timedelta) -> list:
    cutoff = datetime.now() - window
    return [f for f in failed if f.timestamp >= cutoff]


def _build_coin_breakdown(trades: list[TradeRecord]) -> list[dict]:
    """Coin bazında stats, PNL'e göre azalan sırada."""
    coins = defaultdict(lambda: {
        "trades": 0, "win": 0, "loss": 0, "pnl": 0.0,
        "best_pct": None, "best_atr": None,
        "worst_pct": None, "worst_atr": None,
        "exits": defaultdict(int),
    })
    for t in trades:
        c = coins[t.symbol]
        c["trades"] += 1
        if t.is_profit:
            c["win"] += 1
        else:
            c["loss"] += 1
        c["pnl"] += t.pnl
        c["exits"][t.exit_type] += 1
        if c["best_pct"] is None or t.pnl_pct > c["best_pct"]:
            c["best_pct"] = t.pnl_pct
            c["best_atr"] = t.pnl_atr
        if c["worst_pct"] is None or t.pnl_pct < c["worst_pct"]:
            c["worst_pct"] = t.pnl_pct
            c["worst_atr"] = t.pnl_atr

    sorted_coins = sorted(
        coins.items(), key=lambda kv: kv[1]["pnl"], reverse=True
    )
    return [{"symbol": s, **stats} for s, stats in sorted_coins]


def _format_exit_count(exits: dict) -> str:
    parts = []
    mapping = [
        ("outer_band_exit", "Dış"),
        ("breakeven_exit", "BE"),
        ("ce_exit", "CE"),
        ("winrate_exit", "Win"),
        ("stoploss", "SL"),
    ]
    for key, label in mapping:
        if exits.get(key, 0) > 0:
            parts.append(f"{label}:{exits[key]}")
    return " ".join(parts) if parts else "—"


def _open_positions_block(state: StateManager, tickers: dict[str, float]) -> str:
    """Açık pozisyonların anlık durumu."""
    if not state.positions:
        return "AÇIK POZİSYON YOK"
    lines = [f"AÇIK POZİSYONLAR: {len(state.positions)}"]
    for sym, pos in state.positions.items():
        cur = tickers.get(sym, pos.entry_price)
        if pos.side == "long":
            pct = (cur - pos.entry_price) / pos.entry_price * 100 if pos.entry_price else 0
            atr_u = (cur - pos.entry_price) / pos.entry_atr if pos.entry_atr else 0
        else:
            pct = (pos.entry_price - cur) / pos.entry_price * 100 if pos.entry_price else 0
            atr_u = (pos.entry_price - cur) / pos.entry_atr if pos.entry_atr else 0
        side_label = "Long" if pos.side == "long" else "Short"
        be_str = _fmt_price(pos.be_level) if pos.be_level else "—"
        ce_str = _fmt_price(pos.ce_level) if pos.ce_level else "—"
        lines.append(
            f"┌─ {sym} — {side_label} ─────────\n"
            f"│ Giriş: {_fmt_price(pos.entry_price)}\n"
            f"│ Şu an: {_fmt_price(cur)} ({_fmt_pct(pct)} | {_fmt_atr(atr_u)})\n"
            f"│ Seviye: {pos.level.label}\n"
            f"│ CE: {ce_str} | BE: {be_str}\n"
            f"└──────────────────────"
        )
    return "\n".join(lines)


def build_hourly_report(state: StateManager,
                        tickers: dict[str, float]) -> str:
    """Saatlik rapor (son 1 saat)."""
    trades = _filter_trades(state.trades, timedelta(hours=1))
    total = len(trades)
    win = sum(1 for t in trades if t.is_profit)
    loss = total - win
    pnl = sum(t.pnl for t in trades)
    failed = len(_filter_failed(state.failed_signals, timedelta(hours=1)))

    open_block = _open_positions_block(state, tickers)

    text = (
        f"📊 SAATLİK RAPOR — {datetime.now().strftime('%H:%M | %d.%m.%Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"İşlemler: {total} toplam | {win} kâr | {loss} zarar\n"
        f"Açılan: {total} | Açılamayan: {failed}\n"
        f"PNL: {_fmt_pnl(pnl)} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{open_block}"
    )
    return text


def build_12h_report(state: StateManager) -> str:
    """12 saatlik detaylı rapor."""
    trades = _filter_trades(state.trades, timedelta(hours=12))
    return _build_period_report(state, trades, "12 SAATLİK RAPOR", timedelta(hours=12))


def build_daily_z_report(state: StateManager) -> str:
    """Günlük Z raporu (son 24 saat)."""
    trades = _filter_trades(state.trades, timedelta(hours=24))
    return _build_period_report(state, trades, "GÜNLÜK Z RAPORU", timedelta(hours=24),
                                include_finance=True)


def _build_period_report(state: StateManager, trades: list[TradeRecord],
                        title: str, window: timedelta,
                        include_finance: bool = False) -> str:
    total = len(trades)
    win = sum(1 for t in trades if t.is_profit)
    loss = total - win
    winrate = (win / total * 100) if total > 0 else 0
    pnl = sum(t.pnl for t in trades)

    # Ortalamalar
    profit_trades = [t for t in trades if t.is_profit]
    loss_trades = [t for t in trades if not t.is_profit]
    avg_profit_pct = sum(t.pnl_pct for t in profit_trades) / len(profit_trades) if profit_trades else 0
    avg_profit_atr = sum(t.pnl_atr for t in profit_trades) / len(profit_trades) if profit_trades else 0
    avg_loss_pct = sum(t.pnl_pct for t in loss_trades) / len(loss_trades) if loss_trades else 0
    avg_loss_atr = sum(t.pnl_atr for t in loss_trades) / len(loss_trades) if loss_trades else 0
    avg_atr_all = sum(t.pnl_atr for t in trades) / total if total > 0 else 0

    # En iyi / en kötü
    best = max(trades, key=lambda t: t.pnl_pct, default=None)
    worst = min(trades, key=lambda t: t.pnl_pct, default=None)

    # Çıkış tipleri
    exit_counts = defaultdict(int)
    for t in trades:
        exit_counts[t.exit_type] += 1

    # Açılamayanlar
    failed = _filter_failed(state.failed_signals, window)
    failed_reasons = defaultdict(int)
    for f in failed:
        failed_reasons[f.reason] += 1

    # Coin bazında
    coin_stats = _build_coin_breakdown(trades)

    # ----- Metin oluştur -----
    lines = [
        f"📋 {title} — {datetime.now().strftime('%H:%M | %d.%m.%Y')}",
        "━━━━━━━━━━━━━━━━━━━━",
        "GENEL ÖZET",
        f"Toplam İşlem: {total}",
        f"Kârlı: {win} | Zararlı: {loss}",
        f"Winrate: %{winrate:.1f}",
        "",
        "ORTALAMA PERFORMANS",
        f"Ort. Kâr: {_fmt_pct(avg_profit_pct)} | {_fmt_atr(avg_profit_atr)}",
        f"Ort. Zarar: {_fmt_pct(avg_loss_pct)} | {_fmt_atr(avg_loss_atr)}",
        f"Ort. ATR Kâr: {_fmt_atr(avg_atr_all)}",
        "",
    ]

    if best:
        best_side = "Long" if best.side == "long" else "Short"
        lines.append(
            f"EN İYİ İŞLEM: {best.symbol} {best_side} "
            f"{_fmt_pct(best.pnl_pct)} | {_fmt_atr(best.pnl_atr)} | {_fmt_pnl(best.pnl)} USDT"
        )
    if worst:
        worst_side = "Long" if worst.side == "long" else "Short"
        lines.append(
            f"EN KÖTÜ İŞLEM: {worst.symbol} {worst_side} "
            f"{_fmt_pct(worst.pnl_pct)} | {_fmt_atr(worst.pnl_atr)} | {_fmt_pnl(worst.pnl)} USDT"
        )

    lines.append(f"\nToplam PNL: {_fmt_pnl(pnl)} USDT")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # Giriş/çıkış
    lines.append("GİRİŞ/ÇIKIŞ")
    lines.append(f"Açılan: {total}")
    lines.append(f"Açılamayan: {len(failed)}")
    for reason, count in failed_reasons.items():
        label = FAIL_REASON_LABELS.get(reason, reason)
        lines.append(f"  {label}: {count}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("ÇIKIŞ TİPLERİ")
    for key, label in [
        ("outer_band_exit", "Dış bant"),
        ("breakeven_exit", "Breakeven"),
        ("ce_exit", "CE Takip"),
        ("winrate_exit", "Winrate"),
        ("stoploss", "Stoploss"),
    ]:
        count = exit_counts.get(key, 0)
        pct = (count / total * 100) if total > 0 else 0
        lines.append(f"{label}: {count} | %{pct:.1f}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("COİN BAZINDA (PNL azalan)")
    for c in coin_stats:
        symbol = c["symbol"]
        lines.append(
            f"┌─ {symbol} ────────────────\n"
            f"│ İşlem: {c['trades']} | K:{c['win']} Z:{c['loss']}\n"
            f"│ En iyi: {_fmt_pct(c['best_pct'])} | {_fmt_atr(c['best_atr'])}\n"
            f"│ En kötü: {_fmt_pct(c['worst_pct'])} | {_fmt_atr(c['worst_atr'])}\n"
            f"│ PNL: {_fmt_pnl(c['pnl'])} USDT\n"
            f"│ Çıkış: {_format_exit_count(c['exits'])}\n"
            f"└──────────────────────"
        )

    if include_finance and state.start_balance > 0:
        # Bu sadece "günlük PNL" yansıması (sermayeden değil son 24h'dan)
        current_balance = state.start_balance + sum(t.pnl for t in state.trades)
        daily_pct = (pnl / state.start_balance * 100)
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("FİNANSAL ÖZET")
        lines.append(f"Başlangıç Bakiye: {state.start_balance:.2f} USDT")
        lines.append(f"Güncel Bakiye:    {current_balance:.2f} USDT (tahmini)")
        lines.append(f"Günlük PNL:       {_fmt_pnl(pnl)} USDT ({daily_pct:+.2f}%)")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)
