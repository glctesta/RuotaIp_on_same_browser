# db_connection.py
import pyodbc


class DatabaseConnection:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.connection = None

    def connect(self):
        """Crea una connessione al database usando le credenziali crittografate"""
        if self.connection is not None:
            return self.connection

        config = self.config_manager.load_config()

        # Lista dei possibili driver da provare
        drivers = [
            'ODBC Driver 18 for SQL Server',
            'ODBC Driver 17 for SQL Server',
            'SQL Server',
            'SQL Server Native Client 11.0'
        ]

        # Trova il primo driver disponibile
        driver = None
        available_drivers = pyodbc.drivers()
        for d in drivers:
            if d in available_drivers:
                driver = d
                break

        if driver is None:
            raise Exception("Nessun driver SQL Server trovato. Installa un driver ODBC per SQL Server.")

        #print(f"Utilizzo del driver: {driver}")

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={config['server']};"
            f"DATABASE={config['database']};"
            f"UID={config['username']};"
            f"PWD={config['password']};"
            "Trusted_Connection=no;"
            "TrustServerCertificate=yes;"
            "Encrypt=yes;"
            "Connection Timeout=30;"
            "Mars_Connection=yes;"  # Aggiunto per gestire meglio le connessioni multiple
        )

        try:
            self.connection = pyodbc.connect(conn_str)
            self.connection.autocommit = True  # Aggiunto per evitare problemi di transazioni pendenti
            print("Connessione stabilita con successo!")
            return self.connection
        except pyodbc.Error as e:
            print(f"Errore durante la connessione: {str(e)}")
            raise

    def disconnect(self):
        """Chiude la connessione al database"""
        try:
            if self.connection:
                if not self.connection.closed:
                    self.connection.close()
                self.connection = None
        except Exception as e:
            print(f"Errore durante la chiusura della connessione: {str(e)}")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
