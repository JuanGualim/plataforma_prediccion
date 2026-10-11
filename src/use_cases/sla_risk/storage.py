"""Tablas de tickets en PostgreSQL: definición, carga y lectura.

Estrategia de carga: "full refresh". Cada `make data` vacía las tablas y carga el snapshot
completo dentro de UNA transacción: o queda todo cargado o no cambia nada.
Las tablas se crean con SQLAlchemy si no existen; las migraciones versionadas (Alembic)
se dejan para cuando el esquema deba evolucionar con datos que no se pueden regenerar.
"""

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import Engine

from mlplatform.data.db import copy_dataframe
from use_cases.sla_risk.simulator import BUSINESS_TZ

SCHEMA = "support"
TIMESTAMP_COLUMNS = ["created_at", "first_response_at", "resolved_at", "closed_at"]


def build_tables(schema: str = SCHEMA) -> tuple[sa.MetaData, sa.Table, sa.Table]:
    metadata = sa.MetaData(schema=schema)
    tz_ts = sa.DateTime(timezone=True)
    tickets = sa.Table(
        "tickets",
        metadata,
        sa.Column("ticket_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("created_at", tz_ts, nullable=False, index=True),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        sa.Column("customer_tier", sa.Text, nullable=False),
        sa.Column("product", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("sla_hours", sa.Integer, nullable=False),
        sa.Column("open_tickets_in_queue", sa.Integer, nullable=False),
        sa.Column("assigned_group", sa.Text),
        sa.Column("first_response_at", tz_ts),
        sa.Column("reassignment_count", sa.Integer, nullable=False),
        sa.Column("resolved_at", tz_ts),
        sa.Column("closed_at", tz_ts),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("sla_breached", sa.Boolean),  # NULL = resultado aún desconocido
    )
    events = sa.Table(
        "ticket_events",
        metadata,
        sa.Column("event_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey(tickets.c.ticket_id),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("event_at", tz_ts, nullable=False),
    )
    return metadata, tickets, events


def replace_data(
    engine: Engine, tickets: pd.DataFrame, events: pd.DataFrame, schema: str = SCHEMA
) -> None:
    """Atomically replace the content of the tickets and events tables."""
    metadata, tickets_table, events_table = build_tables(schema)
    with engine.begin() as conn:
        conn.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        metadata.create_all(conn)
        conn.execute(sa.text(f'TRUNCATE TABLE "{schema}".ticket_events, "{schema}".tickets'))
        copy_dataframe(conn, tickets[[c.name for c in tickets_table.columns]], schema, "tickets")
        copy_dataframe(
            conn, events[[c.name for c in events_table.columns]], schema, "ticket_events"
        )


def read_tickets(engine: Engine, schema: str = SCHEMA) -> pd.DataFrame:
    """Read tickets with the same dtypes the simulator produces."""
    with engine.connect() as conn:
        df = pd.read_sql_table("tickets", conn, schema=schema)
    df["ticket_id"] = df["ticket_id"].astype(str)  # el driver devuelve uuid.UUID
    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert(BUSINESS_TZ).dt.as_unit("us")
    df["sla_breached"] = df["sla_breached"].astype("boolean")
    return df.sort_values("created_at", kind="stable").reset_index(drop=True)
