"""Bitácora de auditoría del ciclo de vida, en PostgreSQL (implementa lifecycle.EventLog).

Solo se agregan filas; nunca se modifican ni se borran. Vive fuera de MLflow a propósito:
la auditoría debe sobrevivir a un cambio de herramienta de registry y poder consultarse
con SQL ("¿quién promovió qué el mes pasado?").
"""

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import JSONB

from mlplatform.lifecycle.service import RegistryEvent
from mlplatform.serialization import to_jsonable

SCHEMA = "governance"


class PostgresEventLog:
    def __init__(self, engine: Engine, schema: str = SCHEMA) -> None:
        self.engine = engine
        self.schema = schema
        self.metadata = sa.MetaData(schema=schema)
        self.table = sa.Table(
            "model_events",
            self.metadata,
            sa.Column("event_id", sa.BigInteger, sa.Identity(), primary_key=True),
            sa.Column("model_name", sa.Text, nullable=False, index=True),
            sa.Column("event_type", sa.Text, nullable=False),
            sa.Column("from_version", sa.Text),
            sa.Column("to_version", sa.Text),
            sa.Column("actor", sa.Text, nullable=False),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("details", JSONB, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        with engine.begin() as conn:
            conn.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
            self.metadata.create_all(conn)

    def append(self, event: RegistryEvent) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.table.insert().values(
                    model_name=event.model_name,
                    event_type=event.event_type,
                    from_version=event.from_version,
                    to_version=event.to_version,
                    actor=event.actor,
                    reason=event.reason,
                    details=to_jsonable(event.details),
                    created_at=event.created_at,
                )
            )

    def history(self, model_name: str) -> list[RegistryEvent]:
        query = (
            sa.select(self.table)
            .where(self.table.c.model_name == model_name)
            .order_by(self.table.c.event_id)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [
            RegistryEvent(
                model_name=row["model_name"],
                event_type=row["event_type"],
                from_version=row["from_version"],
                to_version=row["to_version"],
                actor=row["actor"],
                reason=row["reason"],
                details=row["details"],
                created_at=row["created_at"].isoformat(),
            )
            for row in rows
        ]
