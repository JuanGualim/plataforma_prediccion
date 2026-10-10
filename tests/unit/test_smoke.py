"""Prueba trivial: valida que el entorno está instalado y los paquetes se importan."""

import json
import logging

import mlplatform
from mlplatform.config import Settings
from mlplatform.logging_config import JsonFormatter, configure_logging


def test_package_imports() -> None:
    assert mlplatform.__version__ == "0.1.0"


def test_settings_build_database_url_without_leaking_password() -> None:
    settings = Settings(_env_file=None, postgres_password="s3cret")

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "s3cret" in settings.database_url
    assert "s3cret" not in repr(settings)


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "test", "levelname": "INFO", "msg": "hola", "model_version": "3"}
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hola"
    assert payload["model_version"] == "3"


def test_configure_logging_runs() -> None:
    configure_logging(level="DEBUG", fmt="json")

    assert logging.getLogger().level == logging.DEBUG
