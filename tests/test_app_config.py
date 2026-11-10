import logging

import pytest

from app_config import JsonFormatter, configure_logging, load_config


def test_load_config_rejects_live_mode(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    with pytest.raises(ValueError, match="Only EXECUTION_MODE=paper"):
        load_config()


def test_load_config_requires_telegram_pair(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="both TELEGRAM"):
        load_config()


def test_json_formatter_emits_structured_log():
    record = logging.LogRecord("test", logging.INFO, "test.py", 10, "hello %s", ("world",), None)
    output = JsonFormatter().format(record)
    assert '"level": "INFO"' in output
    assert '"message": "hello world"' in output


def test_config_accepts_json_logging(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    cfg = load_config()
    assert cfg.log_format == "json"
