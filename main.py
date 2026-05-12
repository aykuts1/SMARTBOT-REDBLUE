"""
Ana giriş noktası - APScheduler ile 30dk mum kapanış ve 60sn çıkış taraması.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
import strategy
import telegram_bot as tg_fmt
from bybit_client import BybitClient
from position_manager import PositionManager
from telegram_bot import TelegramNotifier


# ============= LOGGING =============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# APScheduler loglarını sustur
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("main")


# ============= GLOBAL STATE =============
class BotState:
    """Bot global state - scheduler job'larından erişilir."""
    client: BybitClient = None
    notifier: TelegramNotifier = None
    pm: PositionManager = None
    stake: float = 0.0
    leverage: int = config.LEVERAGE
    symbols: list = []


STATE = BotState()


# ============= GİRİŞ TARAMASI =============
def entry_scan_job():
    """30dk mum kapanışında çalışır - tüm sembolleri tarar."""
    scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info(f"=== Giriş taraması başladı [{scan_time}] ===")

    opened = []
    filter_rejections = []
    max_pos_skips = []
    duplicate_skips = []

    # Mum kapanışından sonra Bybit'in verileri güncellemesi için kısa bekleme
    time.sleep(3)

    for symbol in STATE.symbols:
        try:
            # Veri çek
            df_30m = STATE.client.fetch_klines(
                symbol, config.KLINE_INTERVAL_30M, config.KLINE_LIMIT
            )
            df_2h = STATE.client.fetch_klines(
                symbol, config.KLINE_INTERVAL_2H, config.KLINE_LIMIT
            )
        except Exception as e:
            logger.warning(f"{symbol}: kline hata - {e}")
            continue

        # Strateji değerlendir
        try:
            result = strategy.evaluate_symbol(df_30m, df_2h, symbol)
        except Exception as e:
            logger.error(f"{symbol}: strateji hata - {e}")
            continue

        # Crossover var ama filtreye takıldı?
        if result.crossover_happened and not result.has_signal:
            filter_rejections.append(
                (symbol, result.crossover_side, result.rejection_reason or "?")
            )
            # Tek tek anlık bildirim de gönderelim
            STATE.notifier.send(tg_fmt.fmt_filter_reject(
                symbol, result.crossover_side, result.rejection_reason or "?"
            ))
            continue

        if not result.has_signal:
            continue

        # ===== SİNYAL VAR =====
        side = result.side

        # Aynı coinde pozisyon var mı?
        if STATE.pm.has(symbol):
            duplicate_skips.append((symbol, side))
            STATE.notifier.send(tg_fmt.fmt_duplicate(symbol, side))
            continue

        # 5 pozisyon dolu mu?
        if STATE.pm.count() >= config.MAX_POSITIONS:
            max_pos_skips.append((symbol, side))
            STATE.notifier.send(tg_fmt.fmt_max_positions(symbol, side))
            continue

        # CE ve ATR hesapla
        try:
            initial_ce = strategy.compute_initial_ce(df_30m, side)
            entry_atr = strategy.compute_entry_atr(df_30m)
        except Exception as e:
            logger.error(f"{symbol}: CE/ATR hesap hata - {e}")
            continue

        # Pozisyon aç
        try:
            pos = STATE.pm.open_position(
                symbol=symbol,
                side=side,
                df_30m=df_30m,
                initial_ce=initial_ce,
                entry_atr=entry_atr,
            )
        except Exception as e:
            logger.error(f"{symbol}: pozisyon açma hata - {e}")
            STATE.notifier.send(tg_fmt.fmt_error(f"{symbol} open", str(e)))
            continue

        if pos is None:
            logger.info(f"{symbol}: pozisyon açılamadı")
            continue

        opened.append((symbol, side))
        STATE.notifier.send(tg_fmt.fmt_entry(
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            qty=pos.qty,
            stop_price=pos.current_stop,
            ce_price=pos.ce_level,
            stake=pos.stake,
            leverage=STATE.leverage,
        ))

    # ===== ÖZET MESAJI =====
    try:
        summary = tg_fmt.fmt_scan_summary(
            scan_time=scan_time,
            total_symbols=len(STATE.symbols),
            opened=opened,
            filter_rejections=filter_rejections,
            max_pos_skips=max_pos_skips,
            duplicate_skips=duplicate_skips,
            open_count=STATE.pm.count(),
            stake=STATE.stake,
            leverage=STATE.leverage,
        )
        STATE.notifier.send(summary)
    except Exception as e:
        logger.error(f"Özet mesajı hata - {e}")

    logger.info(
        f"=== Giriş taraması bitti: açılan={len(opened)}, "
        f"filtre={len(filter_rejections)}, max={len(max_pos_skips)}, "
        f"duplicate={len(duplicate_skips)} ==="
    )


# ============= ÇIKIŞ TARAMASI =============
def exit_scan_job():
    """Her 60 saniyede çalışır - açık pozisyonları kontrol eder."""
    if STATE.pm.count() == 0:
        return

    def kline_fetcher(symbol):
        try:
            return STATE.client.fetch_klines(
                symbol, config.KLINE_INTERVAL_30M, config.KLINE_LIMIT
            )
        except Exception as e:
            logger.warning(f"{symbol}: exit scan kline hata - {e}")
            return None

    try:
        closed = STATE.pm.scan_exits(kline_fetcher)
    except Exception as e:
        logger.error(f"Çıkış taraması hata - {e}")
        STATE.notifier.send(tg_fmt.fmt_error("exit scan", str(e)))
        return

    for pos, reason, exit_price, pnl_usdt, pnl_pct in closed:
        STATE.notifier.send(tg_fmt.fmt_exit(
            symbol=pos.symbol,
            side=pos.side,
            exit_price=exit_price,
            reason=reason,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
        ))


# ============= BAŞLANGIÇ =============
def initialize() -> None:
    """Bot'u başlat: validasyon, client, bakiye, kaldıraç, instrument cache."""
    # 1) Config validate
    config.validate()

    # 2) Client ve notifier
    STATE.client = BybitClient()
    STATE.notifier = TelegramNotifier(
        config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID
    )

    # 3) Bakiye oku ve stake hesapla (BOT ÖMRÜ BOYUNCA SABİT)
    try:
        balance = STATE.client.fetch_usdt_balance()
    except Exception as e:
        logger.critical(f"Bakiye alınamadı - {e}")
        STATE.notifier.send(tg_fmt.fmt_error("startup balance", str(e)))
        raise

    if balance <= 0:
        msg = f"Bakiye 0 veya negatif: {balance}"
        STATE.notifier.send(tg_fmt.fmt_error("startup", msg))
        raise RuntimeError(msg)

    STATE.stake = balance * config.STAKE_PERCENT
    STATE.symbols = list(config.SYMBOLS)

    logger.info(
        f"Bakiye: {balance:.2f} USDT, Stake: {STATE.stake:.2f} USDT, "
        f"Kaldıraç: {config.LEVERAGE}x, Sembol: {len(STATE.symbols)}"
    )

    # 4) Tüm semboller için kaldıraç set et + instrument cache'le
    failed_symbols = []
    for sym in STATE.symbols:
        try:
            STATE.client.fetch_instrument_info(sym)
            STATE.client.set_leverage(sym, config.LEVERAGE)
        except Exception as e:
            logger.warning(f"{sym}: kaldıraç/instrument set hata - {e}")
            failed_symbols.append(sym)

    if failed_symbols:
        STATE.symbols = [s for s in STATE.symbols if s not in failed_symbols]
        logger.warning(
            f"{len(failed_symbols)} sembol listeden çıkarıldı: {failed_symbols}"
        )

    # 5) Position manager
    STATE.pm = PositionManager(
        client=STATE.client,
        notifier=STATE.notifier,
        stake_per_trade=STATE.stake,
    )

    # 6) Başlangıç bildirimi
    STATE.notifier.send(tg_fmt.fmt_startup(
        balance=balance,
        stake=STATE.stake,
        leverage=config.LEVERAGE,
        symbol_count=len(STATE.symbols),
    ))


# ============= MAIN =============
def main():
    logger.info("=== Bybit Scalp Bot başlıyor ===")

    try:
        initialize()
    except Exception as e:
        logger.critical(f"Başlangıç hatası - {e}", exc_info=True)
        sys.exit(1)

    scheduler = BlockingScheduler(timezone="UTC")

    # 30 dakikalık mum kapanışı: her saatin 00 ve 30. dakikası
    # Bybit mum kapanışı + 3sn gecikme job içinde uygulanıyor
    scheduler.add_job(
        entry_scan_job,
        trigger=CronTrigger(minute="0,30", second=2, timezone="UTC"),
        id="entry_scan",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # Çıkış taraması: her 60 saniyede
    scheduler.add_job(
        exit_scan_job,
        trigger=IntervalTrigger(seconds=config.EXIT_SCAN_INTERVAL_SEC),
        id="exit_scan",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
        # İlk çalıştırma: hemen değil 30sn sonra (pozisyon yoksa zaten skip eder)
        next_run_time=datetime.now(timezone.utc),
    )

    # Graceful shutdown
    def shutdown_handler(signum, _frame):
        logger.info(f"Sinyal {signum} alındı, scheduler durduruluyor...")
        try:
            STATE.notifier.send("🛑 Bot durduruldu (sinyal)")
        except Exception:
            pass
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    logger.info("Scheduler başlatılıyor (30dk entry + 60sn exit)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.critical(f"Scheduler hatası - {e}", exc_info=True)
        try:
            STATE.notifier.send(tg_fmt.fmt_error("scheduler", str(e)))
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
