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


def test_alert_delay_can_be_set(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[alerts]\nafter_minutes = 10\n")

    assert config.load(path).alert_after_minutes == 10
    assert config.load(tmp_path / "absent.toml").alert_after_minutes == 3


def test_mobile_data_cannot_be_switched_on(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[mobile_data]\nenabled = true\n")

    with pytest.raises(ValueError, match="keeps mobile data off"):
        config.load(path)


@pytest.mark.parametrize(
    "written", ["myteam", "myteam.cloudflareaccess.com", "https://myteam.cloudflareaccess.com/"]
)
def test_reads_cloudflare_access_settings(tmp_path, written):
    path = tmp_path / "config.toml"
    path.write_text(f'[access]\nteam_domain = "{written}"\naudience = "abc123"\n')

    settings = config.load(path)

    assert settings.access.issuer == "https://myteam.cloudflareaccess.com"
    assert settings.access.audience == "abc123"
    assert settings.allow_unauthenticated is False


def test_access_is_not_configured_and_not_waived_by_default(tmp_path):
    settings = config.load(tmp_path / "absent.toml")

    assert settings.access is None
    assert settings.allow_unauthenticated is False


def test_half_configured_access_is_an_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[access]\nteam_domain = "myteam"\n')

    with pytest.raises(ValueError, match="both team_domain and audience"):
        config.load(path)


def test_language_defaults_to_chinese_and_can_be_english(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('language = "en"\n')

    assert config.load(tmp_path / "absent.toml").language == "zh"
    assert config.load(path).language == "en"


def test_unsupported_language_is_an_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('language = "fr"\n')

    with pytest.raises(ValueError, match='language must be "zh" or "en"'):
        config.load(path)
