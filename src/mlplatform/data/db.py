"""Acceso a PostgreSQL."""

import pandas as pd
from psycopg import sql
from sqlalchemy import Connection, Engine, create_engine

from mlplatform.config import get_settings


def get_engine(url: str | None = None) -> Engine:
    """SQLAlchemy engine for the configured database (pool_pre_ping survives DB restarts)."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


def copy_dataframe(conn: Connection, df: pd.DataFrame, schema: str, table: str) -> int:
    """Bulk-insert a DataFrame with PostgreSQL COPY inside the caller's transaction.

    COPY envía todas las filas en un solo flujo en vez de un INSERT por fila; para
    decenas de miles de filas es un orden de magnitud más rápido que `DataFrame.to_sql`.
    """
    # Postgres no entiende NaN/NaT ni tipos numpy: se convierten a objetos Python y None.
    records = df.astype(object).where(df.notna(), None)
    statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(col) for col in df.columns),
    )
    raw = conn.connection.driver_connection
    with raw.cursor() as cursor, cursor.copy(statement) as copy:
        for row in records.itertuples(index=False, name=None):
            copy.write_row(row)
    return len(df)
