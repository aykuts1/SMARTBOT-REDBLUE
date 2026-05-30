"""
🚀 BOT ANA GİRİŞ NOKTASI

Yeni eklemeler:
- External pozisyon yükleme KALDIRILDI (madde 6)
- Başlangıçta otomatik flag scan (madde 56)
- Thread auto-recovery (madde 57)
- Scheduler kendi koruması (madde 58)
- Shutdown'da açık işlem uyarısı (madde 59)
- SIGTERM güvenliği (madde 60)
"""
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from config_loader import Config
from data_manager import DataManager
from trade_manager import TradeManager
from telegram_thread import TelegramThread
from red_thread import RedThread
from blue_thread import BlueThread
from yellow_thread import YellowThread


# =========================================================================
# LOGGING
# =========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("Main")


# =========================================================================
# BOT
# =========================================================================
class Bot:

    def __init__(self):
        log.info("Bot başlatılıyor...")
        self.cfg = Config("config.json")

        # Telegram'ı önce kur (Data Manager hatalarını bildirebilsin diye)
        self.tg = TelegramThread(self.cfg, data_manager=None,
                                 trade_manager_ref=None, control_ref=None)

        # Data Manager
        self.dm = DataManager(self.cfg, telegram_notifier=self.tg)
        self.tg.dm = self.dm

        # Trade Manager
        self.tm = TradeManager(self.cfg, self.dm, self.tg)
        self.tg.set_trade_manager(self.tm)

        # External pozisyon yükleme YOK (madde 6 — kaldırıldı)

        # Thread'ler
        self.red_thread = RedThread(self.cfg, self.dm, self.tm, None, None)
        self.blue_thread = BlueThread(self.cfg, self.dm, self.tm)
        self.yellow_thread = YellowThread(self.cfg, self.dm, self.tm)
        self.red_thread.set_thread_refs(self.blue_thread, self.yellow_thread)

        # Telegram'a kontrol referansı
        self.tg.set_control(self)

        # Scheduler
        self._scheduler_stop = threading.Event()
        self._scheduler_thread = None
        self._running = False
        self._shutdown_requested = threading.Event()

        # Zamanlama state
        self._last_15m_close = None
        self._last_stake_update_ts = time.time()

    # ---------------------------------------------------------------------
    def is_running(self):
        return self._running

    def start_trading(self):
        if self._running:
            return
        log.info("Trading başlatılıyor.")

        # Ölmüş thread'leri yeniden yarat
        if not self.red_thread.is_alive():
            self.red_thread = RedThread(self.cfg, self.dm, self.tm, None, None)
        if not self.blue_thread.is_alive():
            self.blue_thread = BlueThread(self.cfg, self.dm, self.tm)
        if not self.yellow_thread.is_alive():
            self.yellow_thread = YellowThread(self.cfg, self.dm, self.tm)
        self.red_thread.set_thread_refs(self.blue_thread, self.yellow_thread)

        self.red_thread.start()
        self.blue_thread.start()
        self.yellow_thread.start()

        # Pozisyon önbelleğini ilk başta doldur — Mavi/Sarı yanlış pozitif
        # "Kırmızı Bybit'te yok" alarmı vermesin diye.
        try:
            log.info("Başlangıç pozisyon senkronizasyonu yapılıyor...")
            self.dm.sync_open_positions()
        except Exception as e:
            log.exception(f"Başlangıç pozisyon senkron hatası: {e}")

        # Madde 56: başlangıçta otomatik flag taraması (boundary beklemeden)
        try:
            log.info("Başlangıç flag taraması yapılıyor...")
            self.red_thread.scan_flags()
        except Exception as e:
            log.exception(f"Başlangıç flag scan hatası: {e}")

        # 15dk takip için ilk boundary'i set et
        self._last_15m_close = self._current_15m_period()

        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, name="Scheduler", daemon=True)
        self._scheduler_thread.start()
        self._running = True

    def stop_trading(self):
        if not self._running:
            return
        log.info("Trading durduruluyor.")
        self._scheduler_stop.set()
        self.red_thread.stop()
        self.blue_thread.stop()
        self.yellow_thread.stop()
        for t in (self.red_thread, self.blue_thread, self.yellow_thread):
            try:
                t.join(timeout=8)
            except Exception:
                pass
        self._running = False

    # ---------------------------------------------------------------------
    @staticmethod
    def _current_15m_period():
        now = datetime.now(tz=timezone.utc)
        minute_bucket = (now.minute // 15) * 15
        return now.replace(minute=minute_bucket, second=0, microsecond=0)

    def _scheduler_loop(self):
        """
        Master zamanlayıcı:
        - Her 1sn fiyat çek
        - Her 1sn açık pozisyonları senkronize et (Mavi/Sarı için)
        - 15dk mum kapanışında mum verisi çek + flag scan
        - 12h stake güncelle
        - Her tick thread sağlık kontrolü (auto-recovery)
        """
        log.info("Scheduler başladı.")
        last_price_fetch = 0.0
        last_position_sync = 0.0
        while not self._scheduler_stop.is_set():
            now = time.time()

            # Fiyat çekme
            if now - last_price_fetch >= self.cfg.price_update_interval_sec:
                try:
                    self.dm.fetch_all_prices()
                except Exception as e:
                    log.exception(f"Fiyat çekme hatası: {e}")
                last_price_fetch = now

            # Pozisyon senkron (Mavi/Sarı bağlı Kırmızı kontrolü için)
            if now - last_position_sync >= self.cfg.position_sync_interval_sec:
                try:
                    self.dm.sync_open_positions()
                except Exception as e:
                    log.exception(f"Pozisyon senkron hatası: {e}")
                last_position_sync = now

            # 15dk kontrol
            try:
                self._check_15m_close()
            except Exception as e:
                log.exception(f"15dk check hatası: {e}")

            # 12h stake
            try:
                self._check_stake_update()
            except Exception as e:
                log.exception(f"Stake update hatası: {e}")

            # Thread auto-recovery
            try:
                self._check_thread_health()
            except Exception as e:
                log.exception(f"Thread health check hatası: {e}")

            time.sleep(0.5)
        log.info("Scheduler durdu.")

    def _check_15m_close(self):
        if self._last_15m_close is None:
            self._last_15m_close = self._current_15m_period()
            return

        current_period = self._current_15m_period()
        if current_period > self._last_15m_close:
            self._last_15m_close = current_period
            log.info(f"15dk mum kapandı: {current_period.isoformat()}. Mum çekiliyor...")
            try:
                self.dm.fetch_all_candles()
                self.red_thread.scan_flags()
            except Exception as e:
                log.exception(f"15dk işlem hatası: {e}")

    def _check_stake_update(self):
        if (time.time() - self._last_stake_update_ts) >= self.cfg.stake_update_interval_hours * 3600:
            self._last_stake_update_ts = time.time()
            try:
                bal = self.dm.update_balance()
                new_stake = self.tm.update_stake()
                self.tg.notify_stake_update(new_stake, bal)
            except Exception as e:
                log.exception(f"Stake update hatası: {e}")

    def _check_thread_health(self):
        """Madde 57: Bir thread çökmüşse otomatik yeniden başlat."""
        if not self._running:
            return

        # Kırmızı
        if not self.red_thread.is_alive():
            log.error("Kırmızı thread çökmüş, yeniden başlatılıyor...")
            self.tg.notify_critical("Kırmızı thread çöktü", "Otomatik yeniden başlatılıyor.")
            self.red_thread = RedThread(self.cfg, self.dm, self.tm,
                                        self.blue_thread, self.yellow_thread)
            self.red_thread.start()

        # Mavi
        if not self.blue_thread.is_alive():
            log.error("Mavi thread çökmüş, yeniden başlatılıyor...")
            self.tg.notify_critical("Mavi thread çöktü", "Otomatik yeniden başlatılıyor.")
            self.blue_thread = BlueThread(self.cfg, self.dm, self.tm)
            self.blue_thread.start()
            self.red_thread.set_thread_refs(self.blue_thread, self.yellow_thread)

        # Sarı
        if not self.yellow_thread.is_alive():
            log.error("Sarı thread çökmüş, yeniden başlatılıyor...")
            self.tg.notify_critical("Sarı thread çöktü", "Otomatik yeniden başlatılıyor.")
            self.yellow_thread = YellowThread(self.cfg, self.dm, self.tm)
            self.yellow_thread.start()
            self.red_thread.set_thread_refs(self.blue_thread, self.yellow_thread)

    # ---------------------------------------------------------------------
    def run(self):
        # Telegram önce başla
        self.tg.start()
        time.sleep(1.0)

        # Bot başladı bildirimi
        self.tg.notify_bot_started(self.cfg.to_dict())

        # Trading başlat
        self.start_trading()

        # Sinyal yakalama — sys.exit() kullanma (madde 60)
        def _signal_handler(signum, frame):
            log.info(f"Sinyal alındı ({signum}), kapatma başlatılıyor...")
            self._shutdown_requested.set()

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        # Ana thread bekler, shutdown bayrağını kontrol eder
        try:
            while not self._shutdown_requested.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self._shutdown_requested.set()

        self.shutdown()

    def shutdown(self):
        log.info("Shutdown başladı.")

        # Madde 59: Açık işlemler varsa uyar
        try:
            open_trades = self.tm.slots.get_all_open() if self.tm else []
            if open_trades:
                summary = ", ".join(f"{t.symbol}({t.thread})" for t in open_trades[:8])
                self.tg.notify_critical(
                    f"Bot kapanıyor — {len(open_trades)} açık işlem var",
                    f"Açık işlemler otomatik kapatılmıyor. Manuel takip gerekebilir.\n{summary}"
                )
        except Exception:
            pass

        try:
            self.tg.notify_bot_stopped()
        except Exception:
            pass

        self.stop_trading()
        self.dm.stop()
        try:
            self.tg.stop()
            self.tg.join(timeout=5)
        except Exception:
            pass

        log.info("Shutdown tamamlandı.")


# =========================================================================
def main():
    bot = Bot()
    bot.run()


if __name__ == "__main__":
    main()
