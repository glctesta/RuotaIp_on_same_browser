# config_manager.py
from cryptography.fernet import Fernet
import json
import os


class ConfigManager:
    def __init__(self, key_file='encryption_key.key', config_file='db_config.enc'):
        self.key_file = key_file
        self.config_file = config_file

    def generate_key(self):
        """Genera una chiave di crittografia e la salva in un file"""
        key = Fernet.generate_key()
        with open(self.key_file, 'wb') as key_file:
            key_file.write(key)

    def load_key(self):
        """Carica la chiave di crittografia dal file"""
        if not os.path.exists(self.key_file):
            self.generate_key()
        with open(self.key_file, 'rb') as key_file:
            return key_file.read()

    def save_config(self, driver, server, database, username, password):
        """Salva le credenziali del database in modo crittografato"""
        config = {
            'driver': driver,
            'server': server,
            'database': database,
            'username': username,
            'password': password
        }

        key = self.load_key()
        f = Fernet(key)
        encrypted_config = f.encrypt(json.dumps(config).encode())

        with open(self.config_file, 'wb') as config_file:
            config_file.write(encrypted_config)

    def load_config(self):
        """Carica e decritta le credenziali del database"""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError("File di configurazione non trovato")

        key = self.load_key()
        f = Fernet(key)

        with open(self.config_file, 'rb') as config_file:
            encrypted_config = config_file.read()

        decrypted_config = f.decrypt(encrypted_config)
        return json.loads(decrypted_config)
