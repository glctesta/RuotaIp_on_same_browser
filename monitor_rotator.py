"""
Monitor Rotator - Ruota le pagine dei monitor di produzione in Chrome kiosk.

Sorgente delle URL (in ordine di priorita'):
  1. monitor_config.json -> chiave "monitors" (se presente e non vuota)
     Formato flessibile:
       "monitors": [
         "http://10.0.0.21:5065",                   # URL gia' pronta
         {"ip": "10.0.0.22", "port": 8080},         # oggetto ip+port (http://)
         {"ip": "app.local", "port": 443, "scheme": "https"}
       ]
  2. Fallback: tabella [Employee].[dbo].[ExternalIps]
     (solo se non ci sono voci valide nel JSON)

L'intervallo di rotazione si configura in monitor_config.json.
Su PC multi-monitor, imposta "monitor_index" (0-based) nel JSON per
scegliere su quale schermo aprire Chrome.

Chrome si apre in kiosk (schermo intero). Uscita: Alt+F4 o Ctrl+C.
"""

import json
import logging
import os
import signal
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

from screeninfo import get_monitors
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def _app_dir() -> str:
    """Cartella in cui cercare i file di configurazione.

    - In EXE PyInstaller onefile: cartella dell'eseguibile (sys.executable),
      NON la cartella di estrazione temporanea (sys._MEIPASS) che cambia
      ogni avvio.
    - In esecuzione normale Python: cartella dello script.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(_app_dir(), "monitor_config.json")
LOG_FILE = os.path.join(_app_dir(), "monitor_rotator.log")


def _setup_logging() -> logging.Logger:
    """Configura logging su file (rotante) + console.

    File: monitor_rotator.log nella stessa cartella dell'eseguibile/script.
    Rotazione a 2 MB, 5 file di backup, così il log non cresce all'infinito.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (rotante)
    try:
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"ATTENZIONE: impossibile creare log file {LOG_FILE}: {e}")

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Cattura eccezioni non gestite (anche thread principale)
    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Eccezione NON gestita:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _excepthook
    return logger


log = _setup_logging()

MONITOR_QUERY = """
    SELECT [ExternalIP], [Port]
    FROM [Employee].[dbo].[ExternalIps]
    WHERE Dateout IS NULL AND ShowOnProductionMonitors = 1
"""


def _normalize_monitor_entry(entry) -> str | None:
    """
    Accetta una stringa (URL completa) oppure un dict con chiavi ip/port/scheme
    e ritorna una URL pronta all'uso. Ritorna None se la voce e' invalida.
    """
    if isinstance(entry, str):
        s = entry.strip()
        if not s:
            return None
        if "://" in s:
            return s
        return f"http://{s}"
    if isinstance(entry, dict):
        ip = (entry.get("ip") or entry.get("host") or "").strip()
        if not ip:
            return None
        port = entry.get("port")
        scheme = (entry.get("scheme") or "http").strip()
        if port is None or port == "":
            return f"{scheme}://{ip}"
        return f"{scheme}://{ip}:{port}"
    return None


def load_monitors_from_config(config: dict) -> list[str]:
    """Ritorna la lista URL valide lette dal JSON (array 'monitors')."""
    raw = config.get("monitors") or []
    if not isinstance(raw, list):
        return []
    urls = [u for u in (_normalize_monitor_entry(e) for e in raw) if u]
    return urls


def load_monitors_from_db() -> list[str]:
    """Carica la lista URL monitor dalla tabella ExternalIps."""
    # Import lazy: il DB serve solo se il JSON non ha monitors configurati.
    from config_manager import ConfigManager
    from db_connection import DatabaseConnection

    cm = ConfigManager()
    db = DatabaseConnection(cm)
    try:
        conn = db.connect()
        cursor = conn.cursor()
        cursor.execute(MONITOR_QUERY)
        urls = [f"http://{row.ExternalIP}:{row.Port}" for row in cursor.fetchall()]
        cursor.close()
    finally:
        db.disconnect()
    return urls


def load_config() -> dict:
    """Carica la configurazione dal file JSON."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
            log.debug("Config caricato da %s: %s", CONFIG_FILE, cfg)
            return cfg
    except FileNotFoundError:
        log.warning("File di configurazione non trovato: %s", CONFIG_FILE)
        log.info("Creazione con valori default (5 minuti, monitors vuoto)...")
        default = {"interval_minutes": 5, "monitor_index": 0, "monitors": []}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    except json.JSONDecodeError as e:
        log.exception("JSON non valido in %s: %s", CONFIG_FILE, e)
        raise


def list_monitors() -> list:
    """Ritorna la lista dei monitor rilevati (ordine di sistema, 0-based)."""
    try:
        return list(get_monitors())
    except Exception as e:
        log.exception("Impossibile rilevare monitor: %s", e)
        return []


def pick_target_monitor(monitor_index: int):
    """
    Sceglie il monitor target dato l'indice (0-based).
    Se l'indice e' fuori range, ripiega sul monitor principale (indice 0).
    Ritorna un oggetto screeninfo.Monitor oppure None se nessun monitor rilevato.
    """
    monitors = list_monitors()
    if not monitors:
        return None
    if 0 <= monitor_index < len(monitors):
        return monitors[monitor_index]
    log.warning(
        "monitor_index=%s fuori range (%s monitor). Uso il principale.",
        monitor_index, len(monitors),
    )
    return monitors[0]


def create_kiosk_browser(target_monitor=None) -> webdriver.Chrome:
    """
    Crea un'istanza Chrome posizionata sul monitor target e poi fullscreen.

    Nota: --kiosk da riga di comando IGNORA --window-position (bug noto di
    Chrome su Windows multi-monitor). La strategia corretta e':
      1) avviare Chrome NON in kiosk, con un user-data-dir dedicato (niente
         stato pregresso che sovrascriva la posizione);
      2) forzare posizione+dimensione con set_window_rect();
      3) entrare in fullscreen tramite API Selenium.
    """
    options = Options()

    # User-data-dir dedicato (temporaneo) per evitare che Chrome ripristini
    # la posizione dell'ultima sessione sul monitor sbagliato.
    import tempfile
    user_data_dir = tempfile.mkdtemp(prefix="monitor_rotator_chrome_")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    log.debug("Chrome user-data-dir: %s", user_data_dir)

    # Posizione e dimensione iniziali (backup, per i casi in cui Chrome le rispetti).
    if target_monitor is not None:
        x, y = target_monitor.x, target_monitor.y
        w, h = target_monitor.width, target_monitor.height
        options.add_argument(f"--window-position={x},{y}")
        options.add_argument(f"--window-size={w},{h}")

    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-session-crashed-bubble")
    options.add_argument("--disable-features=TranslateUI")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    log.info("Avvio webdriver.Chrome ...")
    try:
        driver = webdriver.Chrome(options=options)
        log.info("Chrome avviato correttamente.")
    except Exception as e:
        log.exception("webdriver.Chrome() FALLITO: %s", e)
        raise

    # Forza posizione+dimensione via DevTools: funziona sempre, anche quando
    # Chrome ignora --window-position.
    if target_monitor is not None:
        try:
            driver.set_window_rect(
                x=target_monitor.x,
                y=target_monitor.y,
                width=target_monitor.width,
                height=target_monitor.height,
            )
            # Pausa breve per lasciare che il window manager applichi lo spostamento
            time.sleep(0.5)
        except Exception as e:
            log.exception("set_window_rect fallito: %s", e)

    # Fullscreen via API (equivalente kiosk). La finestra resta sul monitor corrente.
    try:
        driver.fullscreen_window()
    except Exception as e:
        log.exception("fullscreen_window fallito: %s", e)

    return driver


def print_available_monitors(monitors: list) -> None:
    """Stampa la lista dei monitor rilevati."""
    if not monitors:
        log.warning("Nessun monitor rilevato.")
        return
    log.info("Monitor fisici disponibili:")
    for i, m in enumerate(monitors):
        primary = " [PRIMARIO]" if getattr(m, "is_primary", False) else ""
        name = getattr(m, "name", None) or f"Monitor{i}"
        log.info("  [%d] %s  %dx%d  @ (%d,%d)%s", i, name, m.width, m.height, m.x, m.y, primary)


def main():
    log.info("=" * 60)
    log.info("Monitor Rotator avviato. PID=%s  frozen=%s", os.getpid(), getattr(sys, "frozen", False))
    log.info("App dir: %s", _app_dir())
    log.info("Config:  %s", CONFIG_FILE)
    log.info("Log:     %s", LOG_FILE)
    log.info("Python:  %s", sys.version.replace("\n", " "))
    log.info("=" * 60)

    config = load_config()
    interval = config.get("interval_minutes", 5)
    monitor_index = int(config.get("monitor_index", 0))

    # Rileva monitor fisici e sceglie il target
    all_monitors = list_monitors()
    print_available_monitors(all_monitors)
    target_monitor = pick_target_monitor(monitor_index)
    if target_monitor is not None:
        log.info(
            "-> Chrome sul monitor [%d] %dx%d @ (%d,%d)",
            monitor_index, target_monitor.width, target_monitor.height,
            target_monitor.x, target_monitor.y,
        )
        log.info("   (Modifica 'monitor_index' in monitor_config.json per cambiare)")
    else:
        log.info("Proseguo senza posizionamento esplicito (monitor principale di default).")

    # 1) Priorita': lista 'monitors' nel JSON
    urls = load_monitors_from_config(config)
    source = "monitor_config.json"

    # 2) Fallback: tabella [Employee].[dbo].[ExternalIps]
    if not urls:
        try:
            urls = load_monitors_from_db()
            source = "[Employee].[dbo].[ExternalIps]"
        except Exception as e:
            log.exception("Fallback DB non disponibile: %s", e)
            sys.exit(1)

    if not urls:
        log.error("Nessun monitor configurato.")
        log.error("  - aggiungi voci in monitor_config.json (array 'monitors'), oppure")
        log.error("  - popola la tabella [Employee].[dbo].[ExternalIps].")
        sys.exit(1)

    log.info("Caricati %d monitor da %s:", len(urls), source)
    for u in urls:
        log.info("  - %s", u)
    log.info("Rotazione ogni %s minuti (da monitor_config.json)", interval)
    log.info("Premi Ctrl+C per fermare.")

    driver = create_kiosk_browser(target_monitor=target_monitor)

    def cleanup(_sig=None, _frame=None):
        log.info("Chiusura Chrome (segnale ricevuto)...")
        try:
            driver.quit()
        except Exception as e:
            log.exception("Errore in driver.quit() durante cleanup: %s", e)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Helper per ricarica a caldo del config. Ritorna (urls, interval).
    def _reload_runtime_config(current_urls, current_interval):
        try:
            cfg = load_config()
        except Exception as e:
            log.exception("Config invalido, mantengo lista precedente: %s", e)
            return current_urls, current_interval

        new_interval = int(cfg.get("interval_minutes", current_interval))
        # Lista URL: JSON prioritario, DB solo se vuoto
        new_urls = load_monitors_from_config(cfg)
        if not new_urls:
            try:
                new_urls = load_monitors_from_db()
            except Exception as e:
                log.exception("DB non disponibile in reload: %s", e)
                new_urls = current_urls  # mantieni la lista attuale

        if not new_urls:
            return current_urls, new_interval

        # Log solo se qualcosa e' cambiato
        if new_urls != current_urls:
            log.info("Config RICARICATA: %d monitor", len(new_urls))
            for u in new_urls:
                log.info("  - %s", u)
        if new_interval != current_interval:
            log.info("Intervallo: %s -> %s minuti", current_interval, new_interval)

        return new_urls, new_interval

    idx = 0
    try:
        while True:
            url = urls[idx % len(urls)]
            log.info("Monitor: %s", url)
            try:
                driver.get(url)
            except Exception as e:
                log.exception("driver.get(%s) FALLITO: %s", url, e)
                # continua con il prossimo giro invece di uscire
            idx += 1
            time.sleep(interval * 60)

            # Ricarica config prima di passare alla URL successiva
            urls, interval = _reload_runtime_config(urls, interval)
            # Se la lista e' cambiata, riparte dall'inizio (idx ripartente)
            if idx >= len(urls):
                idx = 0
    except KeyboardInterrupt:
        log.info("Interrotto da tastiera (Ctrl+C).")
    except Exception as e:
        log.exception("Errore nel loop principale: %s", e)
    finally:
        log.info("Uscita: chiusura driver Chrome.")
        try:
            driver.quit()
        except Exception as e:
            log.exception("Errore in driver.quit() finale: %s", e)
        log.info("Monitor Rotator terminato.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("CRASH in main(): %s", e)
        raise
