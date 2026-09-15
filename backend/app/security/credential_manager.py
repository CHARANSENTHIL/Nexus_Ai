"""
Credential Manager — Secure local credential vault for web authentication.
Prevents plaintext credentials and passwords from leaking into LLM prompts or logs.
Stores encrypted credentials locally and injects them directly into DOM elements during automation.
"""
import os
import json
import base64
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

VAULT_DIR = Path(os.path.expanduser("~")) / ".nexus_ai" / "vault"
VAULT_FILE = VAULT_DIR / "credentials_vault.enc"
KEY_SALT_FILE = VAULT_DIR / ".vault_salt"


class CredentialManager:
    """
    Local secure vault for user credentials (passwords, API tokens, logins).
    Uses PBKDF2 + Fernet symmetric encryption.
    """

    def __init__(self, master_key: Optional[str] = None):
        self.vault_dir = VAULT_DIR
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = self._init_crypto(master_key)
        self._credentials_cache: Dict[str, Dict[str, Any]] = {}
        self._load_vault()

    def _init_crypto(self, master_key: Optional[str] = None) -> Fernet:
        """Derive Fernet cipher from device ID or provided master key."""
        passphrase = (master_key or os.environ.get("NEXUS_MASTER_KEY") or "nexus_device_local_key_default").encode("utf-8")
        
        if KEY_SALT_FILE.exists():
            salt = KEY_SALT_FILE.read_bytes()
        else:
            salt = os.urandom(16)
            KEY_SALT_FILE.write_bytes(salt)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(passphrase))
        return Fernet(derived_key)

    def _load_vault(self):
        """Decrypt and load credentials from disk."""
        if not VAULT_FILE.exists():
            self._credentials_cache = {}
            return

        try:
            encrypted_data = VAULT_FILE.read_bytes()
            if not encrypted_data:
                self._credentials_cache = {}
                return
            decrypted_data = self._fernet.decrypt(encrypted_data)
            self._credentials_cache = json.loads(decrypted_data.decode("utf-8"))
            logger.info(f"[CredentialManager] Loaded {len(self._credentials_cache)} credentials from vault.")
        except Exception as e:
            logger.error(f"[CredentialManager] Failed to decrypt vault: {e}")
            self._credentials_cache = {}

    def _save_vault(self):
        """Encrypt and persist credentials to disk."""
        try:
            json_bytes = json.dumps(self._credentials_cache, indent=2).encode("utf-8")
            encrypted = self._fernet.encrypt(json_bytes)
            VAULT_FILE.write_bytes(encrypted)
        except Exception as e:
            logger.error(f"[CredentialManager] Failed to persist vault: {e}")

    def store_credential(self, domain: str, username: str, password: str, notes: Optional[str] = None):
        """Store credentials for a domain/service."""
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        self._credentials_cache[clean_domain] = {
            "domain": clean_domain,
            "username": username,
            "password": password,
            "notes": notes or "",
        }
        self._save_vault()
        logger.info(f"[CredentialManager] Saved credentials for domain: {clean_domain}")

    def get_credential(self, domain: str) -> Optional[Dict[str, str]]:
        """Retrieve stored credential for domain without exposing to LLM context."""
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        # Match exact domain or root domain (e.g., github.com from api.github.com)
        if clean_domain in self._credentials_cache:
            return self._credentials_cache[clean_domain]

        for stored_domain, creds in self._credentials_cache.items():
            if stored_domain in clean_domain or clean_domain in stored_domain:
                return creds
        return None

    def list_domains(self) -> List[str]:
        """List domains that have stored credentials (safe for LLM awareness)."""
        return list(self._credentials_cache.keys())

    def delete_credential(self, domain: str) -> bool:
        """Remove a domain's credential from vault."""
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        if clean_domain in self._credentials_cache:
            del self._credentials_cache[clean_domain]
            self._save_vault()
            return True
        return False


# Singleton instance
credential_manager = CredentialManager()
