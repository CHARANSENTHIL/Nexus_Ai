"""
User Profile Store — Local persistent store for user form data, preferences, and personal details.
Used by Browser Work Agent and other agents for high-accuracy autonomous form filling.
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

PROFILE_DIR = Path(os.path.expanduser("~")) / ".nexus_ai" / "profile"
PROFILE_FILE = PROFILE_DIR / "user_profile.json"


class UserProfileStore:
    """Stores user identity attributes for autofilling web forms and document generation."""

    def __init__(self):
        self.profile_dir = PROFILE_DIR
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._profile: Dict[str, Any] = {}
        self._load_profile()

    def _load_profile(self):
        if not PROFILE_FILE.exists():
            # Initial default template
            self._profile = {
                "personal": {
                    "full_name": "Charan",
                    "first_name": "Charan",
                    "last_name": "",
                    "email": "charanharshini7@gmail.com",
                    "phone": "",
                    "date_of_birth": "",
                },
                "address": {
                    "street": "",
                    "city": "",
                    "state": "",
                    "postal_code": "",
                    "country": "India",
                },
                "work": {
                    "job_title": "Software Engineer",
                    "company": "",
                    "github_username": "",
                    "linkedin_url": "",
                },
                "preferences": {
                    "browser": "msedge",
                    "downloads_directory": str(Path(os.path.expanduser("~")) / "Downloads"),
                }
            }
            self._save_profile()
            return

        try:
            self._profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"[UserProfileStore] Failed to load profile: {e}")
            self._profile = {}

    def _save_profile(self):
        try:
            PROFILE_FILE.write_text(json.dumps(self._profile, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[UserProfileStore] Failed to save profile: {e}")

    def get_profile(self) -> Dict[str, Any]:
        """Return the entire user profile dictionary."""
        return self._profile

    def update_field(self, section: str, key: str, value: Any):
        """Update a specific field in the user profile."""
        if section not in self._profile:
            self._profile[section] = {}
        self._profile[section][key] = value
        self._save_profile()
        logger.info(f"[UserProfileStore] Updated {section}.{key}")

    def find_matching_field(self, field_name: str, placeholder: str = "", label: str = "") -> Optional[str]:
        """
        Smart matcher that checks form input names/labels against known profile fields.
        """
        target = f"{field_name} {placeholder} {label}".lower()

        # Email
        if "email" in target or "e-mail" in target or "mail" in target:
            return self._profile.get("personal", {}).get("email")

        # Full Name
        if "full name" in target or "your name" in target:
            return self._profile.get("personal", {}).get("full_name")
        if "first name" in target or "fname" in target:
            return self._profile.get("personal", {}).get("first_name")
        if "last name" in target or "lname" in target:
            return self._profile.get("personal", {}).get("last_name")

        # Phone
        if "phone" in target or "mobile" in target or "contact number" in target or "tel" in target:
            return self._profile.get("personal", {}).get("phone")

        # Address
        if "street" in target or "address 1" in target or "address line" in target:
            return self._profile.get("address", {}).get("street")
        if "city" in target:
            return self._profile.get("address", {}).get("city")
        if "state" in target or "province" in target:
            return self._profile.get("address", {}).get("state")
        if "zip" in target or "postal" in target or "pincode" in target:
            return self._profile.get("address", {}).get("postal_code")
        if "country" in target:
            return self._profile.get("address", {}).get("country")

        # Work
        if "company" in target or "organization" in target:
            return self._profile.get("work", {}).get("company")
        if "title" in target or "designation" in target or "role" in target:
            return self._profile.get("work", {}).get("job_title")

        return None


# Singleton instance
user_profile_store = UserProfileStore()
