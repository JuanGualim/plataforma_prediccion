"""Carga y lectura reales contra PostgreSQL (requiere `make up`).

Usa un esquema temporal para no tocar los datos de `make data`.
"""

import pandas as pd
import pytest
import sqlalchemy as sa

from mlplatform.data.db import get_engine
from use_cases.sla_risk.storage import read_tickets, replace_data

pytestmark = pytest.mark.integration
TEST_SCHEMA = "support_test"


@pytest.fixture
def engine():
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError:
        pytest.skip("PostgreSQL no disponible: ejecuta `make up`")
    yield engine
    with engine.begin() as conn:
        conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
    engine.dispose()


def test_roundtrip_preserves_data(engine, small_sim) -> None:
    replace_data(engine, small_sim.tickets, small_sim.events, schema=TEST_SCHEMA)

    loaded = read_tickets(engine, schema=TEST_SCHEMA)

    pd.testing.assert_frame_equal(
        loaded, small_sim.tickets, check_dtype=False, check_index_type=False
    )
    # Nombres de columna str "puros": scikit-learn ignora subclases de str.
    assert all(type(col) is str for col in loaded.columns)


def test_replace_is_idempotent(engine, small_sim) -> None:
    replace_data(engine, small_sim.tickets, small_sim.events, schema=TEST_SCHEMA)
    replace_data(engine, small_sim.tickets, small_sim.events, schema=TEST_SCHEMA)

    with engine.connect() as conn:
        n_tickets = conn.execute(sa.text(f'SELECT count(*) FROM "{TEST_SCHEMA}".tickets'))
        n_events = conn.execute(sa.text(f'SELECT count(*) FROM "{TEST_SCHEMA}".ticket_events'))
        assert n_tickets.scalar() == len(small_sim.tickets)
        assert n_events.scalar() == len(small_sim.events)
