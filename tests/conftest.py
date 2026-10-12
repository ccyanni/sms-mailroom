import pytest

from mailroom import i18n


@pytest.fixture(autouse=True)
def english_by_default(monkeypatch):
    """Tests read the page in English unless they are about language."""
    monkeypatch.setattr(i18n, "DEFAULT_LANGUAGE", "en")
