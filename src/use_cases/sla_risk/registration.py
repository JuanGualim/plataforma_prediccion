"""Registra un entrenamiento del modelo de SLA en MLflow como versión candidata."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from mlplatform.lifecycle.contract import contract_violations
from mlplatform.registry.mlflow_registry import ChildRun, TrainingRunRecord, log_and_register
from use_cases.sla_risk.contract import MODEL_NAME, build_contract
from use_cases.sla_risk.dataset import select_features
from use_cases.sla_risk.features import SKOPS_TRUSTED_TYPES
from use_cases.sla_risk.train import TrainingOutcome

EXPERIMENT = "sla_risk"
METRIC_KEYS = ("pr_auc", "roc_auc", "brier", "log_loss")


@dataclass(frozen=True)
class RegisteredCandidate:
    model_name: str
    version: str
    run_id: str
    violations: list[str]


def _finite(metrics: dict, prefix: str, keys=METRIC_KEYS) -> dict[str, float]:
    return {f"{prefix}{k}": float(metrics[k]) for k in keys if metrics.get(k) is not None}


def register_candidate(
    outcome: TrainingOutcome,
    tickets: pd.DataFrame,
    model_name: str = MODEL_NAME,
    experiment: str = EXPERIMENT,
    tracking_uri: str | None = None,
) -> RegisteredCandidate:
    report = outcome.report
    contract = build_contract(report, tickets, model_name)
    violations = contract_violations(contract)
    example = select_features(tickets.head(5))
    test = report["test"]
    git = report["lineage"]["git"]

    record = TrainingRunRecord(
        experiment=experiment,
        run_name=f"{report['selected']['name']}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        model_name=model_name,
        model=outcome.model,
        input_example=example,
        output_example=outcome.model.predict_proba(example)[:, 1],
        params={
            **report["config"],
            "selected_model": report["selected"]["name"],
            "validation_cutoff": report["data"]["validation_cutoff"],
            "test_cutoff": report["data"]["test_cutoff"],
            "dataset_fingerprint": contract.dataset.fingerprint,
        },
        metrics={
            **_finite(report["selected"]["validation"], "val_"),
            **_finite(test["model"]["ranking"], "test_"),
            **_finite(test["baseline_priority_x_tier"]["ranking"], "baseline_test_"),
            "threshold": report["threshold"]["value"],
            "test_cost_per_ticket": test["model"]["decision"]["cost_per_ticket"],
            "test_recall": test["model"]["decision"]["recall"],
            "test_precision": test["model"]["decision"]["precision"],
        },
        text_artifacts={
            "report.json": json.dumps(report, indent=2),
            "model_card.md": contract.model_card,
        },
        contract=contract,
        run_tags={
            "use_case": "sla_risk",
            "git_commit": str(git["commit"]),
            "git_dirty": str(git["dirty"]),
        },
        version_tags={
            "status": "candidate",
            "git_commit": str(git["commit"]),
            "threshold": f"{report['threshold']['value']:.2f}",
            "test_pr_auc": f"{test['model']['ranking']['pr_auc']:.4f}",
            "contract_violations": str(len(violations)),
        },
        child_runs=[
            ChildRun(
                name=c["name"],
                params={"complexity": c["complexity"]},
                metrics={**_finite(c, "val_"), "fit_seconds": c["fit_seconds"]},
            )
            for c in report["candidates_validation"]
        ],
        skops_trusted_types=SKOPS_TRUSTED_TYPES,
    )
    registered = log_and_register(record, tracking_uri)
    return RegisteredCandidate(model_name, registered.version, registered.run_id, violations)
