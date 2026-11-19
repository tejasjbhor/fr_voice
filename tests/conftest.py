"""Isolate tests from the developer .env database."""

from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["APP_SECRET"] = "test-secret-key-please-ignore"
os.environ["TEST_OTP"] = "123456"
os.environ["ALLOW_TEST_OTP"] = "1"
os.environ["OPEN_DIALER"] = "0"
os.environ["ADMIN_PIN"] = "2499"
os.environ["SMS_OTP"] = "false"
os.environ.pop("DATABASE_URL", None)

import pytest
from core.db_engine import reset_engine_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine_cache()
    from core.database import setup_database

    setup_database()
    from fastapi.testclient import TestClient
    from telephony.app import create_app

    with TestClient(create_app()) as c:
        yield c
    reset_engine_cache()
