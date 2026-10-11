"""La API en su contenedor, de punta a punta (requiere `make up` y un champion promovido).

1. La versión que sirve es la del alias champion en MLflow.
2. Cada predicción queda registrada en monitoring.predictions con su versión.
"""

import json
import time
import urllib.request
import uuid

import pytest
import sqlalchemy as sa

from mlplatform.data.db import get_engine
from mlplatform.registry.mlflow_registry import MlflowModelRegistry
from mlplatform.serving.prediction_log import PostgresPredictionLog, PredictionRecord
from use_cases.sla_risk.contract import MODEL_NAME

pytestmark = pytest.mark.integration
URL = "http://localhost:8000"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{URL}{path}", timeout=5) as response:
        return json.loads(response.read())


@pytest.fixture(scope="module")
def serving():
    try:
        ready = _get("/ready")
    except OSError:
        pytest.skip("API no disponible o sin champion: ejecuta `make serve`")
    return ready


def test_serves_the_registry_champion(serving) -> None:
    champion = MlflowModelRegistry().get_alias(MODEL_NAME, "champion")

    assert serving["model_version"] == champion
    assert _get("/metadata")["model_version"] == champion


def test_prediction_is_logged_with_its_version(serving) -> None:
    ticket_id = f"IT-{uuid.uuid4().hex[:10]}"
    payload = {
        "instances": [
            {
                "ticket_id": ticket_id,
                "created_at": "2025-08-04T09:00:00-05:00",
                "channel": "chat",
                "category": "network",
                "priority": "medium",
                "customer_tier": "business",
                "product": "fiber_home",
                "sla_hours": 24,
                "open_tickets_in_queue": 90,
            }
        ]
    }
    request = urllib.request.Request(
        f"{URL}/predict",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "x-traffic-source": "synthetic"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.loads(response.read())

    # El registro se escribe después de responder: se espera brevemente.
    query = sa.text(
        "SELECT model_version, score, features->>'channel' AS channel, traffic_source "
        "FROM monitoring.predictions WHERE entity_id = :id"
    )
    row = None
    with get_engine().connect() as conn:
        for _ in range(20):
            row = conn.execute(query, {"id": ticket_id}).mappings().first()
            if row:
                break
            time.sleep(0.25)

    assert row is not None, "prediction was not logged"
    assert row["model_version"] == body["model_version"]
    assert row["score"] == pytest.approx(body["predictions"][0]["score"])
    assert row["channel"] == "chat"
    assert row["traffic_source"] == "synthetic"


def test_prediction_log_round_trip_in_isolated_schema() -> None:
    schema = f"mon_{uuid.uuid4().hex[:8]}"
    engine = get_engine()
    log = PostgresPredictionLog(engine, schema=schema)
    try:
        log.write(
            [
                PredictionRecord(
                    prediction_id=str(uuid.uuid4()),
                    request_id="r1",
                    entity_id="T-1",
                    model_name="m",
                    model_version="7",
                    score=float("nan"),  # se guarda aunque una métrica venga indefinida
                    decision=False,
                    threshold=0.2,
                    features={"x": float("nan"), "y": "a"},
                    predicted_at="2025-08-04T00:00:00+00:00",
                    latency_ms=1.5,
                )
            ]
        )
        with engine.connect() as conn:
            features = conn.execute(
                sa.text(f'SELECT features FROM "{schema}".predictions')
            ).scalar()
        assert features == {"x": None, "y": "a"}
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
