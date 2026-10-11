"""Registro de cada predicción servida (base del monitoreo de la fase 5).

Se guardan las entradas, el score, la decisión y la versión del modelo. Cuando llegue el
resultado real, se cruzará con esta tabla para medir el desempeño en producción, y las
entradas permiten detectar cambios en los datos (drift).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import JSONB

from mlplatform.serialization import to_jsonable

logger = logging.getLogger(__name__)
SCHEMA = "monitoring"


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: str
    request_id: str
    entity_id: str | None  # p. ej. ticket_id; no es una feature
    model_name: str
    model_version: str
    score: float
    decision: bool
    threshold: float
    features: dict
    predicted_at: str
    latency_ms: float
    # "live" o "synthetic" (pruebas de carga, ejemplos, tests). El monitoreo debe ignorar el
    # tráfico sintético: 10.000 copias del mismo ticket parecerían un drift enorme.
    traffic_source: str = "live"


class PredictionLog(Protocol):
    def write(self, records: list[PredictionRecord]) -> None: ...


class PostgresPredictionLog:
    def __init__(self, engine: Engine, schema: str = SCHEMA) -> None:
        self.engine = engine
        self.metadata = sa.MetaData(schema=schema)
        self.table = sa.Table(
            "predictions",
            self.metadata,
            sa.Column("prediction_id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("request_id", sa.Text, nullable=False),
            sa.Column("entity_id", sa.Text, index=True),
            sa.Column("model_name", sa.Text, nullable=False),
            sa.Column("model_version", sa.Text, nullable=False),
            sa.Column("score", sa.Float, nullable=False),
            sa.Column("decision", sa.Boolean, nullable=False),
            sa.Column("threshold", sa.Float, nullable=False),
            sa.Column("features", JSONB, nullable=False),
            sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("latency_ms", sa.Float, nullable=False),
            sa.Column("traffic_source", sa.Text, nullable=False, server_default="live"),
        )
        with engine.begin() as conn:
            conn.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
            self.metadata.create_all(conn)
            # Migración mínima e idempotente para tablas creadas antes de esta columna.
            # Con más cambios de esquema, esto pasaría a migraciones versionadas (Alembic).
            conn.execute(
                sa.text(
                    f'ALTER TABLE "{schema}".predictions '
                    "ADD COLUMN IF NOT EXISTS traffic_source text NOT NULL DEFAULT 'live'"
                )
            )

    def write(self, records: list[PredictionRecord]) -> None:
        """Best effort: a logging failure must never turn a served prediction into an error."""
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.table.insert(),
                    [{**r.__dict__, "features": to_jsonable(r.features)} for r in records],
                )
        except Exception:
            logger.exception("could not write %d prediction records", len(records))
