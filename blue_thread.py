"""
🔵 MAVİ THREAD — YENİ YAPI

Genel mantık:
  - Flag mantığı KALDIRILDI.
  - 5 seviye: MAVİ ENTRY, ST1, ST2, ST3, ST4 (eski FLAG bölgesi MAVİ ENTRY oldu).
  - Tablo: Kırmızı işlem giriş çizgisi ↔ Kırmızı LOSE arası 5 EŞİT parça.

Yön:
  Kırmızı Short → Mavi Long
  Kırmızı Long  → Mavi Short

AÇILIŞ:
  Tablo kurulurken fiyat anında kontrol edilir.
   * Long için: fiyat Kırmızı giriş çizgisinin ÜSTÜNDEYSE → anında aç.
                Altındaysa fiyat çizgiyi yukarı cross edince aç.
   * Short için: fiyat Kırmızı giriş çizgisinin ALTINDAYSA → anında aç.
                 Üstündeyse fiyat çizgiyi aşağı cross edince aç.

YENİDEN GİRİŞ:
  Mavi kapandıktan sonra Kırmızı hâlâ açıksa AYNI mantıkla yeniden açılabilir.
  Sınırsız tekrar.

ÇIKIŞ ÇİZGİSİ (dinamik):
  Hacim = stake × leverage (notional USDT).
  ekleme_fiyat = (hacim × 0.001) / qty

  Long için:
    Başlangıç çıkış çizgisi = Kırmızı giriş − ekleme_fiyat
    Güncelleme tetiği: fiyat ≥ Mavi açılış × 1.002 (sadece BİR KEZ)
    Güncellendiğinde: çıkış çizgisi = Kırmızı giriş + ekleme_fiyat (sabit kalır)
    Çıkış: fiyat çıkış çizgisini AŞAĞI cross → kapan

  Short için (simetrik):
    Başlangıç çıkış çizgisi = Kırmızı giriş + ekleme_fiyat
    Güncelleme tetiği: fiyat ≤ Mavi açılış × 0.998
    Güncellendiğinde: çıkış çizgisi = Kırmızı giriş − ekleme_fiyat
    Çıkış: fiyat çıkış çizgisini YUKARI cross → kapan

KAPATMA SEBEPLERİ (öncelik sırası):
  1) Pozisyon senkron: bağlı Kırmızı Bybit'te yok → anında kapan
  2) Kırmızı LOSE cross → close_red_and_dependents zincirinden Mavi de kapanır
  3) Çıkış çizgisi cross → kapan

SEVİYE GEÇİŞİ:
  ST1/ST2/ST3/ST4 cross → seviye yükselir.
  ÇIKIŞI ETKİLEMEZ — sadece bilgi/telemetri.

İPTAL EDİLEN:
  Eski 2 eşik trail mantığı (ST1/ST2→Kırmızı giriş, ST3/ST4→ST1).

Hızlı tarama: 1 sn (config'den).
"""
import threading
import logging

from utils import crossed_up, crossed_down

log = logging.getLogger("BlueThread")


class BlueTable:
    """
    Bir Kırmızı işleme bağlı Mavi tablo.
    State machine değil — flag yok, sadece açık işlem var/yok durumu.
    """
    __slots__ = ("red_trade_id", "red_side", "symbol", "side",
                 "levels", "lose_line", "entry_line",
                 "current_level", "active_trade",
                 "initial_checked")

    def __init__(self, red_trade, levels):
        self.red_trade_id = red_trade.id
        self.red_side = red_trade.side
        self.symbol = red_trade.symbol
        # Mavi yön Kırmızı'nın tersi
        self.side = "LONG" if red_trade.side == "SHORT" else "SHORT"
        self.levels = dict(levels)  # ST1..ST4 çizgileri
        self.lose_line = red_trade.lose_line  # Kırmızı LOSE
        self.entry_line = red_trade.level_lines["ENTRY"]  # Kırmızı işlem giriş çizgisi
        self.current_level = None  # işlem açık değilken None
        self.active_trade = None
        self.initial_checked = False  # tablo kurulduktan sonra ilk fiyat kontrolü yapıldı mı


class BlueThread(threading.Thread):

    LEVEL_ORDER = ["MAVİ ENTRY", "ST1", "ST2", "ST3", "ST4"]

    def __init__(self, config, data_manager, trade_manager):
        super().__init__(name="BlueThread", daemon=True)
        self.cfg = config
        self.dm = data_manager
        self.tm = trade_manager
        self._stop = threading.Event()
        # red_trade_id -> BlueTable
        self.tables = {}
        self.tables_lock = threading.Lock()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # OKUMA HELPERS (raporlar için)
    # ------------------------------------------------------------------
    def get_open_flags(self):
        """
        Mavi'de flag mantığı yok. Geriye dönük uyumluluk için boş liste döner
        (telegram_thread bu fonksiyonu çağırıyor olabilir).
        """
        return []

    # ------------------------------------------------------------------
    # TABLO OLUŞTURMA — Kırmızı açılınca çağrılır
    # ------------------------------------------------------------------
    def create_table_for_red(self, red_trade):
        """
        Kırmızı işlem açıldığında Mavi tablosunu kurar.
        Tablo: Kırmızı giriş ↔ Kırmızı LOSE arası 5 eşit parça.
        """
        entry = red_trade.level_lines["ENTRY"]
        lose = red_trade.lose_line
        step = (lose - entry) / 5.0
        levels = {
            "ST1": entry + step * 1,
            "ST2": entry + step * 2,
            "ST3": entry + step * 3,
            "ST4": entry + step * 4,
        }

        table = BlueTable(red_trade, levels)
        with self.tables_lock:
            self.tables[red_trade.id] = table

        # Telegram bildirim
        all_lines = {
            "Kırmızı Giriş": entry,
            **levels,
            "Kırmızı LOSE": lose,
        }
        self.tm.tg.notify_thread_ready(red_trade, "BLUE", table.side, all_lines)

        return table

    def remove_table_for_red(self, red_trade_id):
        """Kırmızı kapanınca çağrılır (close_red_and_dependents tarafından dolaylı)."""
        with self.tables_lock:
            self.tables.pop(red_trade_id, None)

    # ------------------------------------------------------------------
    # BÖLGE TESPİTİ (sadece seviye telemetrisi için)
    # ------------------------------------------------------------------
    def _find_zone(self, tbl, price):
        """
        Fiyat hangi bölgede? Mavi tablosuna göre yön bilinçli.
        Dönüş: "MAVİ ENTRY", "ST1".."ST4" veya None (tablo dışı).
        """
        entry = tbl.entry_line
        lose = tbl.lose_line
        levels = tbl.levels

        if tbl.side == "LONG":
            # Kırmızı Short, Mavi Long → tablo yukarı uzanır
            if price < entry or price > lose:
                return None
            if price < levels["ST1"]:
                return "MAVİ ENTRY"
            if price < levels["ST2"]:
                return "ST1"
            if price < levels["ST3"]:
                return "ST2"
            if price < levels["ST4"]:
                return "ST3"
            return "ST4"
        else:
            # Kırmızı Long, Mavi Short → tablo aşağı uzanır
            if price > entry or price < lose:
                return None
            if price > levels["ST1"]:
                return "MAVİ ENTRY"
            if price > levels["ST2"]:
                return "ST1"
            if price > levels["ST3"]:
                return "ST2"
            if price > levels["ST4"]:
                return "ST3"
            return "ST4"

    # ------------------------------------------------------------------
    # SCAN — her 1 sn'de çağrılır
    # ------------------------------------------------------------------
    def scan(self):
        # 0) Pozisyon senkronizasyonuna bağlı temizlik:
        #    Kırmızı'sı kapanmış / Bybit'te yok olmuş tabloları kaldır.
        self._cleanup_dead_tables()

        with self.tables_lock:
            tbls = list(self.tables.values())

        for tbl in tbls:
            if self._stop.is_set():
                return
            try:
                self._tick_table(tbl)
            except Exception as e:
                log.exception(f"BlueThread tick hatası ({tbl.symbol}): {e}")

    def _cleanup_dead_tables(self):
        """
        - Kırmızı'sı bot hafızasında yoksa veya kapalıysa tabloyu sil.
        - Bybit pozisyon önbelleğinde Kırmızı yoksa (synced olduysa) → Mavi'yi kapat.
        """
        with self.tables_lock:
            ids_snapshot = list(self.tables.items())

        for red_id, tbl in ids_snapshot:
            # Önce: Kırmızı bot hafızasında var mı?
            red = self.tm.slots.get_red_for(tbl.symbol, tbl.red_side)
            red_missing_in_bot = (red is None or red.id != red_id or red.closed)

            # Sonra: Bybit önbelleğinde Kırmızı pozisyon var mı?
            # (sadece senkron yapılmışsa güvenilir)
            red_pidx = 1 if tbl.red_side == "LONG" else 2
            red_missing_on_bybit = False
            if self.dm.positions_synced():
                if not self.dm.is_position_open(tbl.symbol, red_pidx):
                    red_missing_on_bybit = True

            if red_missing_in_bot or red_missing_on_bybit:
                # Önce açık Mavi varsa kapat
                if tbl.active_trade and not tbl.active_trade.closed:
                    reason = ("MAVİ KIRMIZI KAPANDI" if red_missing_in_bot
                              else "MAVİ KIRMIZI BYBIT'TE YOK")
                    curr = self.dm.get_last_price(tbl.symbol)
                    try:
                        self.tm.close_trade(tbl.active_trade, reason, curr)
                    except Exception as e:
                        log.error(f"Mavi acil kapatma hatası ({tbl.symbol}): {e}")
                with self.tables_lock:
                    self.tables.pop(red_id, None)

    # ------------------------------------------------------------------
    # TEK TABLO TICK
    # ------------------------------------------------------------------
    def _tick_table(self, tbl):
        prev, curr = self.dm.get_price_pair(tbl.symbol)
        if curr is None:
            return

        # Aktif işlem kapanmışsa state'i temizle
        if tbl.active_trade and tbl.active_trade.closed:
            tbl.active_trade = None
            tbl.current_level = None

        # ---- A) AÇIK İŞLEM YOKSA: açılış mantığı ----
        if tbl.active_trade is None:
            self._handle_open_logic(tbl, prev, curr)
            return

        # ---- B) AÇIK İŞLEM VARSA: çıkış çizgisi + seviye telemetri ----
        self._handle_active_trade(tbl, prev, curr)

    # ------------------------------------------------------------------
    # AÇILIŞ MANTIĞI (flag yok, anında veya cross ile)
    # ------------------------------------------------------------------
    def _handle_open_logic(self, tbl, prev, curr):
        """
        Tablo kurulduktan sonra ilk fiyat kontrolü + sonraki taramalarda cross.
        """
        entry = tbl.entry_line

        # İlk kontrol: tablo yeni kurulduysa fiyat zaten istenen tarafta mı?
        if not tbl.initial_checked:
            tbl.initial_checked = True
            if tbl.side == "LONG":
                if curr > entry:
                    # Fiyat zaten Kırmızı giriş üstünde, anında aç
                    self._open_blue(tbl, curr)
                    return
            else:
                if curr < entry:
                    # Mavi Short, fiyat zaten Kırmızı giriş altında, anında aç
                    self._open_blue(tbl, curr)
                    return
            # İlk kontrolde uygun tarafta değilse, normal cross akışına geç

        # Sonraki taramalar: cross kontrolü
        if prev is None:
            return  # tek fiyat var, cross hesaplayamayız

        if tbl.side == "LONG":
            if crossed_up(prev, curr, entry):
                self._open_blue(tbl, curr)
        else:
            if crossed_down(prev, curr, entry):
                self._open_blue(tbl, curr)

    def _open_blue(self, tbl, entry_price):
        """Mavi işlem aç + dinamik çıkış çizgisini başlangıç değeriyle kur."""
        red_trade = self.tm.slots.get_red_for(tbl.symbol, tbl.red_side)
        if not red_trade or red_trade.id != tbl.red_trade_id or red_trade.closed:
            return False

        level_lines = {
            "ENTRY": tbl.entry_line,
            **tbl.levels,
            "LOSE": tbl.lose_line,
        }

        # Başlangıç seviyesi fiyatın bulunduğu bölgeye göre belirlenir.
        # Telemetri amaçlı — çıkışı etkilemez.
        initial_zone = self._find_zone(tbl, entry_price) or "MAVİ ENTRY"

        trade = self.tm.open_trade(
            symbol=tbl.symbol, side=tbl.side, thread="BLUE",
            entry_price=entry_price,
            lose_line=tbl.lose_line,
            winrate_line=tbl.lose_line,  # Mavi için "WINRATE" = Kırmızı LOSE
            level_lines=level_lines,
            current_level=initial_zone,
            parent_red_trade=red_trade,
        )
        if not trade:
            return False

        # ----- DİNAMİK ÇIKIŞ ÇİZGİSİ BAŞLANGIÇ DEĞERİ -----
        # Hacim = stake × leverage. open_trade gerçek dolum fiyatına göre yeniden
        # hesaplanmış stake'i kullanır; biz mevcut stake'i kullanıyoruz
        # (kısa süreli olduğu için fark ihmal edilebilir).
        ekleme_fiyat = self._calc_ekleme_fiyat(trade)
        if tbl.side == "LONG":
            trade.exit_line = tbl.entry_line - ekleme_fiyat
        else:
            trade.exit_line = tbl.entry_line + ekleme_fiyat
        trade.exit_line_updated = False

        tbl.active_trade = trade
        tbl.current_level = initial_zone

        log.info(f"[{tbl.symbol}] MAVİ {tbl.side} açıldı @ {trade.entry_price} | "
                 f"başlangıç çıkış çizgisi: {trade.exit_line:.8f}")
        return True

    def _calc_ekleme_fiyat(self, trade):
        """
        ekleme_fiyat = (hacim_usdt × 0.001) / qty
        hacim_usdt   = stake × leverage
        """
        if trade.qty <= 0:
            return 0.0
        stake = self.tm.get_stake()
        hacim_usdt = stake * self.cfg.leverage
        ekleme_usdt = hacim_usdt * 0.001  # %0.1
        return ekleme_usdt / trade.qty

    # ------------------------------------------------------------------
    # AÇIK İŞLEM YÖNETİMİ
    # ------------------------------------------------------------------
    def _handle_active_trade(self, tbl, prev, curr):
        trade = tbl.active_trade
        if trade is None or trade.closed:
            return

        # 1) ÇIKIŞ ÇİZGİSİ GÜNCELLEME (sadece bir kez)
        if not trade.exit_line_updated:
            if tbl.side == "LONG":
                # Tetik: fiyat ≥ Mavi açılış × 1.002
                trigger = trade.entry_price * 1.002
                if curr >= trigger:
                    ekleme = self._calc_ekleme_fiyat(trade)
                    trade.exit_line = tbl.entry_line + ekleme
                    trade.exit_line_updated = True
                    log.info(f"[{tbl.symbol}] MAVİ LONG çıkış çizgisi güncellendi: "
                             f"{trade.exit_line:.8f}")
            else:
                # Mavi Short: Tetik fiyat ≤ açılış × 0.998
                trigger = trade.entry_price * 0.998
                if curr <= trigger:
                    ekleme = self._calc_ekleme_fiyat(trade)
                    trade.exit_line = tbl.entry_line - ekleme
                    trade.exit_line_updated = True
                    log.info(f"[{tbl.symbol}] MAVİ SHORT çıkış çizgisi güncellendi: "
                             f"{trade.exit_line:.8f}")

        # 2) SEVİYE TELEMETRİSİ (sadece bilgi)
        new_zone = self._find_zone(tbl, curr)
        if new_zone and new_zone != tbl.current_level and new_zone in self.LEVEL_ORDER:
            # Sadece ileri yönde değişimleri bildir (Mavi'de tek yönlü)
            try:
                old_idx = self.LEVEL_ORDER.index(tbl.current_level)
            except ValueError:
                old_idx = -1
            new_idx = self.LEVEL_ORDER.index(new_zone)
            if new_idx > old_idx:
                tbl.current_level = new_zone
                trade.current_level = new_zone
                trade.highest_level = new_zone
                self.tm.tg.notify_level_change(trade, new_zone)

        # 3) ÇIKIŞ KONTROLÜ
        if prev is None or trade.exit_line is None:
            return

        if tbl.side == "LONG":
            # Long çıkış: fiyat çıkış çizgisini AŞAĞI cross
            if crossed_down(prev, curr, trade.exit_line):
                reason = ("MAVİ ÇIKIŞ ÇİZGİSİ (güncellendi)"
                          if trade.exit_line_updated
                          else "MAVİ ÇIKIŞ ÇİZGİSİ (başlangıç)")
                self.tm.close_trade(trade, reason, curr)
                tbl.active_trade = None
                tbl.current_level = None
                tbl.initial_checked = False  # yeniden giriş için sıfırla
        else:
            # Short çıkış: fiyat çıkış çizgisini YUKARI cross
            if crossed_up(prev, curr, trade.exit_line):
                reason = ("MAVİ ÇIKIŞ ÇİZGİSİ (güncellendi)"
                          if trade.exit_line_updated
                          else "MAVİ ÇIKIŞ ÇİZGİSİ (başlangıç)")
                self.tm.close_trade(trade, reason, curr)
                tbl.active_trade = None
                tbl.current_level = None
                tbl.initial_checked = False

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def run(self):
        log.info("Mavi thread başladı.")
        scan_interval = self.cfg.thread_scan_interval_sec
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception as e:
                log.exception(f"BlueThread döngü hatası: {e}")
            self._stop.wait(scan_interval)
        log.info("Mavi thread durdu.")
