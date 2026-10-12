"""Every test gets its own empty database, upload folder and cache, and fresh rate limits."""

import pytest

from app import cache, limits, mailer, retention, store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "tally.db")
    monkeypatch.setattr(retention, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(cache, "ROOT", tmp_path / "cache")
    try:
        from app import main
        monkeypatch.setattr(main, "UPLOADS", tmp_path / "uploads")
        monkeypatch.setattr(main, "HEARTBEAT", tmp_path / "heartbeat")
    except ImportError:
        pass
    (tmp_path / "uploads").mkdir()
    limits.reset()
    mailer.SENT.clear()
    store.init()
    yield tmp_path
