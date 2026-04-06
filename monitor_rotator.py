"""
Monitor Rotator - Ruota le pagine dei monitor di produzione in Chrome kiosk.
Le URL vengono lette dalla tabella [Employee].[dbo].[ExternalIps].
L'intervallo di rotazione e' configurabile in monitor_config.json.

Chrome si apre in modalita' kiosk (schermo intero, senza barra indirizzi).
Per uscire: Alt+F4 sulla finestra Chrome, oppure Ctrl+C nel terminale.
"""

import json
import os
import signal
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config_manager import ConfigManager
from db_connection import DatabaseConnection

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_config.json")

MONITOR_QUERY = """
    SELECT [ExternalIP], [Port]
    FROM [Employee].[dbo].[ExternalIps]
    WHERE Dateout IS NULL AND ShowOnProductionMonitors = 1
"""


def load_monitors_from_db() -> list[str]:
    """Carica la lista URL monitor dalla tabella ExternalIps."""
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

    if not urls:
        print("ERRORE: nessun monitor trovato nella tabella ExternalIps.")
        sys.exit(1)
    return urls


def load_config() -> dict:
    """Carica la configurazione dal file JSON."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"File di configurazione non trovato: {CONFIG_FILE}")
        print("Creazione con valori default (5 minuti)...")
        default = {"interval_minutes": 5}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default


def create_kiosk_browser() -> webdriver.Chrome:
    """Crea un'istanza Chrome in modalita' kiosk."""
    options = Options()
    options.add_argument("--kiosk")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-default-apps")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=options)
    return driver


def main():
    config = load_config()
    interval = config.get("interval_minutes", 5)

    urls = load_monitors_from_db()
    print(f"Caricati {len(urls)} monitor dal database:")
    for u in urls:
        print(f"  - {u}")
    print(f"\nRotazione ogni {interval} minuti (da monitor_config.json)")
    print("Premi Ctrl+C per fermare.\n")

    driver = create_kiosk_browser()

    def cleanup(_sig=None, _frame=None):
        print("\nChiusura Chrome...")
        try:
            driver.quit()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    idx = 0
    try:
        while True:
            url = urls[idx % len(urls)]
            print(f"[{time.strftime('%H:%M:%S')}] Monitor: {url}")
            driver.get(url)
            idx += 1
            time.sleep(interval * 60)
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
