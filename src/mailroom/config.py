"""Mailroom's settings, read from a file kept outside the repository."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mailroom.access import AccessSettings
from mailroom.telegram import TelegramSettings

DATA_DIR = Path.home() / "Library" / "Application Support" / "Mailroom"
DEFAULT_PATH = DATA_DIR / "config.toml"


@dataclass(frozen=True)
class Config:
    telegram: TelegramSettings | None = None
    alert_after_minutes: float = 3.0
    access: AccessSettings | None = None
    allow_unauthenticated: bool = False  # local development only
    language: str = "zh"  # Telegram texts, and the page until the owner picks another
    backup_dir: Path = DATA_DIR / "backups"
    backup_keep: int = 14


def load(path: Path | None = None) -> Config:
    """Read the config file named by `path`, $MAILROOM_CONFIG or the default location; absent means defaults."""
    path = path or Path(os.environ.get("MAILROOM_CONFIG", DEFAULT_PATH))
    if not path.exists():
        return Config()
    with path.open("rb") as file:
        data = tomllib.load(file)
    telegram = data.get("telegram", {})
    token, chat_id = telegram.get("token"), telegram.get("chat_id")
    if bool(token) != bool(chat_id):
        raise ValueError(f"{path}: [telegram] needs both token and chat_id")
    if data.get("mobile_data", {}).get("enabled", False):
        raise ValueError(f"{path}: [mobile_data] enabled = true is not supported; Mailroom keeps mobile data off")
    access = data.get("access", {})
    team_domain, audience = access.get("team_domain"), access.get("audience")
    if bool(team_domain) != bool(audience):
        raise ValueError(f"{path}: [access] needs both team_domain and audience")
    return Config(
        telegram=TelegramSettings(str(token), str(chat_id)) if token else None,
        alert_after_minutes=float(data.get("alerts", {}).get("after_minutes", 3.0)),
        access=AccessSettings(_team_domain(str(team_domain)), str(audience)) if team_domain else None,
        allow_unauthenticated=bool(access.get("allow_unauthenticated", False)),
        language=_language(path, data.get("language", "zh")),
        backup_dir=Path(data.get("backup", {}).get("directory", DATA_DIR / "backups")).expanduser(),
        backup_keep=int(data.get("backup", {}).get("keep", 14)),
    )


def _language(path: Path, value: object) -> str:
    if value not in ("zh", "en"):
        raise ValueError(f'{path}: language must be "zh" or "en"')
    return str(value)


def _team_domain(value: str) -> str:
    """Accept "team", "team.cloudflareaccess.com" or a full URL."""
    host = value.removeprefix("https://").removeprefix("http://").strip("/")
    return host if "." in host else f"{host}.cloudflareaccess.com"
