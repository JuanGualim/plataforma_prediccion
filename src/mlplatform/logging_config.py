"""Configuración de logging común para todos los procesos de la plataforma.

- Formato `text` para leer en la terminal durante el desarrollo.
- Formato `json` para el serving y el monitoreo: una línea por evento, fácil de
  ingerir en un agregador de logs (Loki, CloudWatch, etc.).

Uso:
    from mlplatform.logging_config import configure_logging
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("modelo cargado", extra={"model_version": "3"})
"""

import json
import logging
import logging.config
from datetime import UTC, datetime

from mlplatform.config import get_settings

# Atributos que todo LogRecord trae de fábrica; lo demás proviene de `extra=`.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Serializa cada registro como un objeto JSON en una sola línea."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Configura el logger raíz. Sin argumentos, usa LOG_LEVEL y LOG_FORMAT."""
    settings = get_settings()
    level = level or settings.log_level
    fmt = fmt or settings.log_format

    formatters = {
        "text": {"format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s"},
        "json": {"()": JsonFormatter},
    }
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {fmt: formatters[fmt]},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": fmt}},
            "root": {"level": level, "handlers": ["console"]},
        }
    )
