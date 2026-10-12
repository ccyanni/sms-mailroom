"""Mailroom's settings, read from a file kept outside the repository."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mailroom.telegram import TelegramSettings

DATA_DIR = Path.home() / "Library" / "Application Support" / "Mailroom"
DEFAULT_PATH = DATA_DIR / "config.toml"


@dataclass(frozen=True)
class Config:
    telegram: TelegramSettings | None = None


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
    return Config(telegram=TelegramSettings(str(token), str(chat_id)) if token else None)
