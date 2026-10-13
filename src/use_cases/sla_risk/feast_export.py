"""CLI: prepara en Postgres las tablas que lee el spike de Feast (fase 6).

    uv run python -m use_cases.sla_risk.feast_export

Feast **no calcula** variables de ventana: guarda series ya calculadas, las une "en el tiempo"
con las filas de entrenamiento y sirve el último valor en línea. El cálculo sigue siendo
nuestro (`context_features`), materializado cada hora:

- feast_spike.operations_hourly: arrivals_24h y breach_rate_7d en cada hora en punto.
- feast_spike.category_hourly: category_queue por categoría en cada hora en punto.
- feast_spike.expected: para cada ticket, el valor exacto en T0 y el de la hora en punto
  anterior. El spike compara lo que devuelve Feast contra esta tabla.

El esquema `feast_spike` es desechable (`make feast-clean`); no lo usa ningún modelo.
"""

import logging

import pandas as pd

from mlplatform.data.db import copy_dataframe, get_engine
from mlplatform.logging_config import configure_logging
from use_cases.sla_risk.context_features import CONTEXT_FEATURES, context_features
from use_cases.sla_risk.fields import CATEGORIES
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)
SCHEMA = "feast_spike"
GLOBAL_FEATURES = ["arrivals_24h", "breach_rate_7d"]

DDL = f"""
DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;
CREATE SCHEMA {SCHEMA};
CREATE TABLE {SCHEMA}.operations_hourly (
    event_timestamp timestamptz PRIMARY KEY,
    arrivals_24h bigint NOT NULL,
    breach_rate_7d double precision NOT NULL
);
CREATE TABLE {SCHEMA}.category_hourly (
    category text NOT NULL,
    event_timestamp timestamptz NOT NULL,
    category_queue bigint NOT NULL,
    PRIMARY KEY (category, event_timestamp)
);
CREATE TABLE {SCHEMA}.expected (
    ticket_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    category text NOT NULL,
    {", ".join(f"exact_{f} double precision NOT NULL" for f in CONTEXT_FEATURES)},
    {", ".join(f"hourly_{f} double precision NOT NULL" for f in CONTEXT_FEATURES)}
);
"""


def hourly_grid(tickets: pd.DataFrame) -> pd.DatetimeIndex:
    start = tickets["created_at"].min().tz_convert("UTC").floor("h")
    end = tickets["created_at"].max().tz_convert("UTC").ceil("h")
    return pd.date_range(start, end, freq="h")


def build_tables(tickets: pd.DataFrame) -> dict[str, pd.DataFrame]:
    hours = hourly_grid(tickets)
    grid = pd.DataFrame(
        {
            "created_at": hours.repeat(len(CATEGORIES)),
            "category": list(CATEGORIES) * len(hours),
        }
    )
    values = pd.concat([grid, context_features(tickets, grid)], axis=1)
    operations = (
        values.drop_duplicates("created_at")[["created_at", *GLOBAL_FEATURES]]
        .rename(columns={"created_at": "event_timestamp"})
        .reset_index(drop=True)
    )
    category = values[["category", "created_at", "category_queue"]].rename(
        columns={"created_at": "event_timestamp"}
    )

    at = tickets[["ticket_id", "created_at", "category"]].copy()
    exact = context_features(tickets, at).add_prefix("exact_")
    floored = at.assign(created_at=at["created_at"].dt.tz_convert("UTC").dt.floor("h"))
    hourly = context_features(tickets, floored).add_prefix("hourly_")
    expected = pd.concat([at, exact, hourly], axis=1)
    expected["ticket_id"] = expected["ticket_id"].astype(str)
    return {"operations_hourly": operations, "category_hourly": category, "expected": expected}


def main() -> int:
    configure_logging()
    engine = get_engine()
    tables = build_tables(read_tickets(engine))
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL)
        for name, frame in tables.items():
            copy_dataframe(conn, frame, SCHEMA, name)
    logger.info(
        "exported %s",
        {name: len(frame) for name, frame in tables.items()},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
