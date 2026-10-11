"""Evaluador del modelo de SLA para la puerta de promoción.

Recalcula, con los datos actuales, las métricas de candidato, champion y baseline sobre la
ventana de prueba del candidato. Cada modelo decide con SU umbral, pero todos se juzgan con
los mismos costos (los del candidato), para que la comparación sea justa.
"""

import pandas as pd

from mlplatform.lifecycle.promotion import Evaluation
from mlplatform.lifecycle.service import LoadedVersion
from mlplatform.training.baselines import GroupRateClassifier
from mlplatform.training.metrics import binary_classification_metrics
from mlplatform.training.thresholds import select_threshold_min_cost, threshold_metrics
from use_cases.sla_risk.dataset import build_splits


class SlaRiskEvaluator:
    def __init__(self, tickets: pd.DataFrame) -> None:
        self.tickets = tickets

    def __call__(self, candidate: LoadedVersion, champion: LoadedVersion | None) -> Evaluation:
        dataset = candidate.contract.dataset
        costs = candidate.contract.threshold.costs
        cost_fp, cost_fn = costs["false_positive"], costs["false_negative"]
        splits = build_splits(
            self.tickets, pd.Timestamp(dataset.train_end), pd.Timestamp(dataset.validation_end)
        )
        test = splits.test

        def evaluate(scores, threshold: float) -> dict[str, float]:
            decision = threshold_metrics(test.y, scores, threshold, cost_fp, cost_fn)
            return {
                **binary_classification_metrics(test.y, scores),
                "cost_per_ticket": decision["cost_per_ticket"],
            }

        def model_scores(loaded: LoadedVersion):
            return loaded.model.predict_proba(test.X)[:, 1]

        baseline = GroupRateClassifier(["priority", "customer_tier"]).fit(
            splits.train.X, splits.train.y
        )
        baseline_threshold = select_threshold_min_cost(
            splits.validation.y, baseline.predict_proba(splits.validation.X)[:, 1], cost_fp, cost_fn
        )

        return Evaluation(
            window_start=str(splits.test_cutoff),
            n=len(test.y),
            candidate=evaluate(model_scores(candidate), candidate.contract.threshold.value),
            champion=evaluate(model_scores(champion), champion.contract.threshold.value)
            if champion
            else None,
            baseline=evaluate(baseline.predict_proba(test.X)[:, 1], baseline_threshold),
        )
