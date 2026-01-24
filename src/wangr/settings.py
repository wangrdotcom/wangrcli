"""Settings management for API key storage and validation."""

import json
import logging
from pathlib import Path
from typing import Final

import requests

from wangr.config import API_TIMEOUT, KEYS_VALIDATE_URL

logger = logging.getLogger(__name__)

CONFIG_DIR: Final[Path] = Path.home() / ".wangr"
CONFIG_FILE: Final[Path] = CONFIG_DIR / "config.json"


def _ensure_config_dir() -> None:
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    """Load configuration from file."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config(config: dict) -> None:
    """Save configuration to file."""
    _ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_api_key() -> str | None:
    """Get the stored API key."""
    config = _load_config()
    return config.get("api_key")


def set_api_key(api_key: str) -> None:
    """Store the API key."""
    config = _load_config()
    config["api_key"] = api_key
    _save_config(config)


def clear_api_key() -> None:
    """Remove the stored API key."""
    config = _load_config()
    config.pop("api_key", None)
    _save_config(config)


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Validate an API key against the server.

    Returns:
        tuple of (is_valid, message)
    """
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty"

    try:
        response = requests.get(
            KEYS_VALIDATE_URL,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=API_TIMEOUT,
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("valid"):
                return True, data.get("message", "API key is valid")
            return False, data.get("message", "Invalid API key")
        elif response.status_code == 401:
            return False, "Invalid API key"
        elif response.status_code == 429:
            return False, "Rate limited. Please try again later."
        else:
            return False, f"Validation failed (status {response.status_code})"
    except requests.exceptions.Timeout:
        return False, "Request timed out. Please try again."
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to server. Check your internet connection."
    except Exception as exc:
        logger.error("API key validation error: %s", exc)
        return False, "Validation failed. Please try again."


def is_api_key_configured() -> bool:
    """Check if an API key is stored."""
    return bool(get_api_key())
