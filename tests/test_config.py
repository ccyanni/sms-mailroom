import pytest

from mailroom import config
from mailroom.telegram import TelegramSettings


def test_missing_file_means_telegram_is_not_set_up(tmp_path):
    assert config.load(tmp_path / "absent.toml").telegram is None


def test_reads_telegram_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\ntoken = "123:abc"\nchat_id = 4242\n')

    assert config.load(path).telegram == TelegramSettings(token="123:abc", chat_id="4242")


def test_half_configured_telegram_is_an_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\ntoken = "123:abc"\n')

    with pytest.raises(ValueError, match="both token and chat_id"):
        config.load(path)
