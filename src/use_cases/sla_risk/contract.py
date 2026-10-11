"""Construye el contrato de despliegue del modelo de SLA a partir de un entrenamiento."""

from datetime import UTC, datetime

import pandas as pd

from mlplatform.data.fingerprint import dataframe_fingerprint
from mlplatform.lifecycle.contract import (
    CodeVersion,
    DataChecks,
    DatasetReference,
    DecisionThreshold,
    Dependencies,
    DeploymentContract,
    ModelSignature,
    SignatureField,
)
from mlplatform.training.lineage import lockfile_sha256
from use_cases.sla_risk.dataset import select_features
from use_cases.sla_risk.fields import FEATURES, TARGET
from use_cases.sla_risk.model_card import OWNER, build_model_card
from use_cases.sla_risk.quality import validate_tickets

MODEL_NAME = "sla_risk"
SOURCE = "postgres:support.tickets"


def build_contract(
    report: dict, tickets: pd.DataFrame, model_name: str = MODEL_NAME
) -> DeploymentContract:
    """`report` is TrainingOutcome.report; `tickets` the exact table the model was trained on."""
    data, cfg = report["data"], report["config"]
    checks = validate_tickets(tickets)
    X = select_features(tickets.head(1))
    test = report["test"]

    return DeploymentContract(
        model_name=model_name,
        use_case="sla_risk",
        owner=OWNER,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        signature=ModelSignature(
            inputs=[SignatureField(name=c, dtype=str(X[c].dtype)) for c in FEATURES],
            output="probabilidad de incumplir el SLA, en [0, 1]",
        ),
        model_card=build_model_card(report, model_name),
        primary_metric=cfg["selection_metric"],
        validation_metrics=report["selected"]["validation"],
        test_metrics={
            **test["model"]["ranking"],
            "cost_per_ticket": test["model"]["decision"]["cost_per_ticket"],
        },
        baseline_test_metrics=test["baseline_priority_x_tier"]["ranking"],
        threshold=DecisionThreshold(
            value=report["threshold"]["value"],
            criterion="minimum expected cost on validation",
            chosen_on="validation",
            costs={
                "false_positive": cfg["cost_false_positive"],
                "false_negative": cfg["cost_false_negative"],
            },
        ),
        dataset=DatasetReference(
            source=SOURCE,
            fingerprint=dataframe_fingerprint(
                tickets, ["ticket_id", *FEATURES, TARGET], sort_by=["ticket_id"]
            ),
            data_start=data["range"][0],
            data_end=data["range"][1],
            train_end=data["validation_cutoff"],
            validation_end=data["test_cutoff"],
            n_rows=data["n"],
        ),
        code=CodeVersion(
            git_commit=report["lineage"]["git"]["commit"],
            git_dirty=report["lineage"]["git"]["dirty"],
        ),
        dependencies=Dependencies(
            lockfile_sha256=lockfile_sha256(), packages=report["lineage"]["environment"]
        ),
        data_checks=DataChecks(passed=checks.ok, issues=checks.issues),
    )
