"""API de predicción con una fuente de modelos en memoria (sin MLflow ni base de datos)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mlplatform.serving.app import create_app
from mlplatform.serving.models import ModelBundle
from use_cases.sla_risk.contract import build_contract
from use_cases.sla_risk.dataset import select_features
from use_cases.sla_risk.fields import FEATURES
from use_cases.sla_risk.serving import SPEC, TicketAtCreation
from use_cases.sla_risk.train import TrainingConfig, train


@pytest.fixture(scope="module")
def trained(small_sim):
    config = TrainingConfig(
        validation_days=7, test_days=7, permutation_repeats=1, candidate_names=("logreg",)
    )
    outcome = train(small_sim.tickets, config)
    return outcome.model, build_contract(outcome.report, small_sim.tickets)


class FakeSource:
    """Registry stand-in: `champion` points to whatever version the test sets."""

    def __init__(self, models: dict, contract) -> None:
        self.models = models
        self.contract = contract
        self.champion: str | None = None
        self.fail_loading = False

    def current_version(self):
        return self.champion

    def load(self, version):
        if self.fail_loading:
            raise RuntimeError("artifact store unreachable")
        return ModelBundle("sla_risk", version, self.models[version], self.contract)


class FakeLog:
    def __init__(self) -> None:
        self.records = []

    def write(self, records):
        self.records.extend(records)


def ticket(**overrides) -> dict:
    base = {
        "ticket_id": "T-1",
        "created_at": "2025-01-20T09:30:00-05:00",
        "channel": "email",
        "category": "hardware",
        "priority": "low",
        "customer_tier": "enterprise",
        "product": "router_x200",
        "sla_hours": 24,
        "open_tickets_in_queue": 120,
    }
    return {**base, **overrides}


@pytest.fixture
def setup(trained):
    model, contract = trained
    source = FakeSource({"1": model, "2": model}, contract)
    source.champion = "1"
    log = FakeLog()
    app = create_app(SPEC, source, log, FakeLog(), refresh_seconds=0, max_batch=5)
    with TestClient(app) as client:
        yield client, source, log, app.state.holder


def test_health_ready_and_metadata(setup) -> None:
    client, *_ = setup

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready", "model_version": "1"}
    metadata = client.get("/metadata").json()
    assert metadata["model_version"] == "1"
    assert metadata["threshold"]["chosen_on"] == "validation"
    assert [i["name"] for i in metadata["inputs"]] == FEATURES


def test_prediction_matches_the_model_exactly(setup, trained, small_sim) -> None:
    """Sin training/serving skew: la API y el pipeline dan el mismo score para el mismo ticket."""
    client, *_ = setup
    model, contract = trained
    rows = small_sim.tickets.head(5)
    instances = [
        {
            "ticket_id": r.ticket_id,
            **{c: getattr(r, c) for c in FEATURES if c != "created_at"},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows.itertuples()
    ]

    response = client.post("/predict", json={"instances": instances}).json()

    expected = model.predict_proba(select_features(rows))[:, 1]
    served = np.array([p["score"] for p in response["predictions"]])
    np.testing.assert_allclose(served, expected, rtol=1e-12)
    threshold = contract.threshold.value
    assert [p["decision"] for p in response["predictions"]] == list(expected >= threshold)
    assert response["model_version"] == "1"


def test_request_id_is_propagated_and_predictions_logged(setup) -> None:
    client, _, log, _ = setup

    response = client.post(
        "/predict", json={"instances": [ticket()]}, headers={"x-request-id": "abc-123"}
    )

    assert response.headers["x-request-id"] == "abc-123"
    assert response.json()["request_id"] == "abc-123"
    record = log.records[-1]
    assert (record.request_id, record.entity_id, record.model_version) == ("abc-123", "T-1", "1")
    assert "ticket_id" not in record.features  # el identificador no es una feature
    assert record.features["channel"] == "email"


def test_traffic_source_is_recorded(setup) -> None:
    client, _, log, _ = setup

    client.post("/predict", json={"instances": [ticket()]})
    client.post(
        "/predict", json={"instances": [ticket()]}, headers={"x-traffic-source": "Synthetic"}
    )
    client.post("/predict", json={"instances": [ticket()]}, headers={"x-traffic-source": "otro"})

    assert [r.traffic_source for r in log.records[-3:]] == ["live", "synthetic", "live"]


def test_unseen_category_is_served(setup) -> None:
    client, *_ = setup

    response = client.post("/predict", json={"instances": [ticket(channel="whatsapp")]})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "bad",
    [
        ticket(created_at="2025-01-20T09:30:00"),  # sin zona horaria
        ticket(sla_hours=0),
        ticket(open_tickets_in_queue=-1),
        ticket(channel=""),
        ticket(resolved_at="2025-01-21T00:00:00-05:00"),  # dato del futuro: campo no permitido
        {k: v for k, v in ticket().items() if k != "priority"},  # falta un campo
    ],
)
def test_invalid_requests_are_rejected(setup, bad) -> None:
    client, *_ = setup

    assert client.post("/predict", json={"instances": [bad]}).status_code == 422


def test_batch_limits(setup) -> None:
    client, *_ = setup

    assert client.post("/predict", json={"instances": []}).status_code == 422
    assert client.post("/predict", json={"instances": [ticket()] * 6}).status_code == 422
    assert client.post("/predict", json={"instances": [ticket()] * 5}).status_code == 200


def test_champion_change_is_picked_up_without_restart(setup) -> None:
    client, source, _, holder = setup

    source.champion = "2"  # p. ej. tras `make promote` o `make rollback`
    assert holder.refresh()

    assert client.post("/predict", json={"instances": [ticket()]}).json()["model_version"] == "2"


def test_failed_load_keeps_serving_the_previous_model(setup) -> None:
    client, source, _, holder = setup
    source.champion, source.fail_loading = "2", True

    assert not holder.refresh()

    assert client.post("/predict", json={"instances": [ticket()]}).json()["model_version"] == "1"
    assert "unreachable" in client.get("/metadata").json()["last_refresh_error"]


def test_not_ready_without_champion(trained) -> None:
    model, contract = trained
    source = FakeSource({"1": model}, contract)  # nadie ha promovido nada todavía

    with TestClient(create_app(SPEC, source, refresh_seconds=0)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/predict", json={"instances": [ticket()]}).status_code == 503


def test_model_whose_contract_does_not_match_the_api_is_refused(trained) -> None:
    model, contract = trained
    other_inputs = contract.signature.model_copy(update={"inputs": contract.signature.inputs[:-1]})
    source = FakeSource({"1": model}, contract.model_copy(update={"signature": other_inputs}))
    source.champion = "1"

    with TestClient(create_app(SPEC, source, refresh_seconds=0)) as client:
        assert client.get("/ready").status_code == 503
        assert "do not match" in client.get("/ready").json()["reason"]


def test_api_schema_matches_model_features() -> None:
    fields = set(TicketAtCreation.model_fields) - {"ticket_id"}

    assert fields == set(FEATURES)


def test_every_predict_call_is_recorded_for_service_monitoring(trained) -> None:
    model, contract = trained
    source = FakeSource({"1": model}, contract)
    source.champion = "1"
    requests_log = FakeLog()
    app = create_app(SPEC, source, None, requests_log, refresh_seconds=0)

    with TestClient(app) as client:
        client.post("/predict", json={"instances": [ticket()]})
        client.post("/predict", json={"instances": [ticket(sla_hours=0)]})  # 422
        client.get("/health")  # no es una predicción: no se registra
        app.state.requests_buffer.flush()

    assert [(r.status, r.model_version) for r in requests_log.records] == [(200, "1"), (422, None)]
    assert all(r.latency_ms > 0 for r in requests_log.records)
