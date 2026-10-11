"""Adaptador de MLflow: tracking de experimentos y model registry (solo MECANISMO).

Las decisiones (¿se promueve?, ¿a qué versión vuelve el rollback?) viven en
mlplatform.lifecycle; este módulo solo traduce esas decisiones a llamadas de MLflow.
"""

import os

# MLflow lee su configuración de variables de entorno. Se fijan aquí, antes de importarlo,
# para que todo proceso de la plataforma se comporte igual:
# - Sin telemetría: la plataforma no envía datos de uso a terceros.
# - Artefactos siempre a través del servidor (modo proxy). Si el cliente pidiera URLs
#   prefirmadas, apuntarían al almacenamiento interno de Docker, inalcanzable desde fuera.
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD", "false")
os.environ.setdefault("MLFLOW_ENABLE_PROXY_MULTIPART_UPLOAD", "false")

import tempfile  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import mlflow  # noqa: E402
from mlflow import MlflowClient  # noqa: E402
from mlflow.models import infer_signature  # noqa: E402

from mlplatform.config import get_settings  # noqa: E402
from mlplatform.lifecycle.contract import DeploymentContract  # noqa: E402

CONTRACT_ARTIFACT = "contract.json"
MODEL_ARTIFACT = "model"


def configure_mlflow(tracking_uri: str | None = None) -> str:
    uri = tracking_uri or get_settings().mlflow_tracking_uri
    mlflow.set_tracking_uri(uri)
    return uri


@dataclass(frozen=True)
class ChildRun:
    name: str
    params: dict[str, Any]
    metrics: dict[str, float]


@dataclass(frozen=True)
class TrainingRunRecord:
    experiment: str
    run_name: str
    model_name: str
    model: Any  # estimador de scikit-learn entrenado
    input_example: Any  # unas filas de entrada (definen la firma)
    output_example: Any  # salida del modelo para esas filas
    params: dict[str, Any]
    metrics: dict[str, float]
    text_artifacts: dict[str, str]  # nombre de archivo -> contenido
    contract: DeploymentContract
    run_tags: dict[str, str] = field(default_factory=dict)
    version_tags: dict[str, str] = field(default_factory=dict)
    child_runs: list[ChildRun] = field(default_factory=list)
    skops_trusted_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegisteredVersion:
    run_id: str
    version: str


def log_and_register(
    record: TrainingRunRecord, tracking_uri: str | None = None
) -> RegisteredVersion:
    """Log a training run (with one child run per candidate) and register its model."""
    configure_mlflow(tracking_uri)
    mlflow.set_experiment(record.experiment)
    with mlflow.start_run(run_name=record.run_name) as run:
        mlflow.set_tags(record.run_tags)
        mlflow.log_params({k: str(v)[:500] for k, v in record.params.items()})
        mlflow.log_metrics(record.metrics)
        for child in record.child_runs:
            with mlflow.start_run(run_name=child.name, nested=True):
                mlflow.log_params(child.params)
                mlflow.log_metrics(child.metrics)
        for name, content in record.text_artifacts.items():
            mlflow.log_text(content, name)
        mlflow.log_text(record.contract.model_dump_json(indent=2), CONTRACT_ARTIFACT)

        info = mlflow.sklearn.log_model(
            record.model,
            name=MODEL_ARTIFACT,
            signature=infer_signature(record.input_example, record.output_example),
            input_example=record.input_example,
            registered_model_name=record.model_name,
            skops_trusted_types=record.skops_trusted_types,
        )
    version = str(info.registered_model_version)
    client = MlflowClient()
    for key, value in record.version_tags.items():
        client.set_model_version_tag(record.model_name, version, key, value)
    return RegisteredVersion(run_id=run.info.run_id, version=version)


class MlflowModelRegistry:
    """Implements the lifecycle.ModelRegistry port on top of the MLflow registry.

    Los modelos se cargan con el sabor (flavor) de scikit-learn porque el evaluador necesita
    `predict_proba`; otro tipo de modelo requeriría su propio cargador.
    """

    def __init__(self, tracking_uri: str | None = None) -> None:
        self.client = MlflowClient(configure_mlflow(tracking_uri))

    def get_alias(self, model_name: str, alias: str) -> str | None:
        return self.client.get_registered_model(model_name).aliases.get(alias)

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        self.client.set_registered_model_alias(model_name, alias, version)

    def set_version_tag(self, model_name: str, version: str, key: str, value: str) -> None:
        self.client.set_model_version_tag(model_name, version, key, value)

    def get_contract(self, model_name: str, version: str) -> DeploymentContract:
        run_id = self.client.get_model_version(model_name, version).run_id
        with tempfile.TemporaryDirectory() as tmp:
            path = mlflow.artifacts.download_artifacts(
                run_id=run_id, artifact_path=CONTRACT_ARTIFACT, dst_path=tmp
            )
            return DeploymentContract.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def load_model(self, model_name: str, version: str) -> Any:
        return mlflow.sklearn.load_model(f"models:/{model_name}/{version}")

    def latest_version(self, model_name: str) -> str:
        versions = self.client.search_model_versions(f"name='{model_name}'")
        if not versions:
            raise LookupError(f"model '{model_name}' has no registered versions")
        return str(max(int(v.version) for v in versions))

    def describe_versions(self, model_name: str) -> list[dict[str, Any]]:
        aliases = self.client.get_registered_model(model_name).aliases
        by_version = {v: a for a, v in aliases.items()}
        return [
            {
                "version": v.version,
                "alias": by_version.get(v.version, ""),
                "status": v.tags.get("status", ""),
                "test_pr_auc": v.tags.get("test_pr_auc", ""),
                "git_commit": v.tags.get("git_commit", "")[:7],
                "created": v.creation_timestamp,
            }
            for v in sorted(
                self.client.search_model_versions(f"name='{model_name}'"),
                key=lambda v: int(v.version),
            )
        ]
