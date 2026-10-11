"""Ciclo de vida completo contra MLflow y PostgreSQL reales (requiere `make up`).

Usa un nombre de modelo, un experimento y un esquema de auditoría únicos, y los borra al final.
"""

import urllib.request
import uuid

import mlflow
import pytest
import sqlalchemy as sa

from mlplatform.config import get_settings
from mlplatform.data.db import get_engine
from mlplatform.lifecycle.promotion import PromotionPolicy
from mlplatform.lifecycle.service import CHAMPION, LifecycleService
from mlplatform.registry.event_log import PostgresEventLog
from mlplatform.registry.mlflow_registry import MlflowModelRegistry
from use_cases.sla_risk.dataset import select_features
from use_cases.sla_risk.evaluation import SlaRiskEvaluator
from use_cases.sla_risk.registration import register_candidate
from use_cases.sla_risk.train import TrainingConfig, train

pytestmark = pytest.mark.integration
CONFIG = TrainingConfig(
    validation_days=7, test_days=7, permutation_repeats=1, candidate_names=("logreg",)
)


class TolerateDirtyTree:
    """Registry wrapper for tests: the working tree may have uncommitted changes while
    developing. Only that contract rule is relaxed; everything else is real."""

    def __init__(self, inner: MlflowModelRegistry) -> None:
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def get_contract(self, model_name, version):
        contract = self.inner.get_contract(model_name, version)
        code = contract.code.model_copy(update={"git_dirty": False})
        return contract.model_copy(update={"code": code})


@pytest.fixture(scope="module")
def env(small_sim):
    try:
        urllib.request.urlopen(f"{get_settings().mlflow_tracking_uri}/health", timeout=2)
    except OSError:
        pytest.skip("MLflow no disponible: ejecuta `make up`")

    suffix = uuid.uuid4().hex[:8]
    model, experiment, schema = f"sla_test_{suffix}", f"sla_test_{suffix}", f"gov_{suffix}"
    engine = get_engine()
    registry = MlflowModelRegistry()
    yield {
        "model": model,
        "experiment": experiment,
        "registry": registry,
        "events": PostgresEventLog(engine, schema=schema),
        "tickets": small_sim.tickets,
    }
    registry.client.delete_registered_model(model)
    registry.client.delete_experiment(
        registry.client.get_experiment_by_name(experiment).experiment_id
    )
    with engine.begin() as conn:
        conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _register(env) -> str:
    outcome = train(env["tickets"], CONFIG)
    registered = register_candidate(
        outcome, env["tickets"], model_name=env["model"], experiment=env["experiment"]
    )
    return registered.version


def _service(env, policy: PromotionPolicy | None = None) -> LifecycleService:
    return LifecycleService(TolerateDirtyTree(env["registry"]), env["events"], policy)


def test_full_lifecycle(env) -> None:
    evaluator = SlaRiskEvaluator(env["tickets"])
    registry, model = env["registry"], env["model"]

    # 1. Registro: la versión queda como candidata, con contrato y model card en MLflow.
    v1 = _register(env)
    assert registry.get_contract(model, v1).model_name == model
    assert registry.get_alias(model, CHAMPION) is None

    # 2. Primera promoción: solo necesita superar al baseline.
    decision = _service(env).promote(model, v1, evaluator, "ci", "v1")
    assert decision.approved, decision.summary()
    assert registry.get_alias(model, CHAMPION) == v1

    # 3. El champion se carga por alias, como lo hará el serving (fase 4).
    champion = mlflow.sklearn.load_model(f"models:/{model}@{CHAMPION}")
    assert champion.predict_proba(select_features(env["tickets"].head(3))).shape == (3, 2)

    # 4. Un candidato idéntico no supera una política exigente: se rechaza, champion no cambia.
    v2 = _register(env)
    strict = PromotionPolicy(min_improvement=0.05)
    assert not _service(env, strict).promote(model, v2, evaluator, "ci", "v2").approved
    assert registry.get_alias(model, CHAMPION) == v1

    # 5. Con la política estándar (no peor que el champion) pasa; luego, rollback.
    v3 = _register(env)
    assert _service(env).promote(model, v3, evaluator, "ci", "v3").approved
    event = _service(env).rollback(model, "ci", "simulacro de incidente")
    assert (event.from_version, event.to_version) == (v3, v1)
    assert registry.get_alias(model, CHAMPION) == v1

    # 6. Todo quedó en la bitácora de auditoría, en orden, y en los tags de cada versión.
    history = [(e.event_type, e.to_version) for e in env["events"].history(model)]
    assert history == [("promoted", v1), ("rejected", v2), ("promoted", v3), ("rolled_back", v1)]
    statuses = {v["version"]: v["status"] for v in registry.describe_versions(model)}
    assert statuses == {v1: "champion", v2: "rejected", v3: "rolled_back"}
