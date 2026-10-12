"""Monitoreo del modelo: ¿sigue acertando cuando llegan los resultados reales?

Las etiquetas llegan tarde (un ticket se sabe incumplido solo al resolverse o al vencer su
plazo), así que siempre se reporta la **cobertura de etiquetas**: qué fracción de las
predicciones ya tiene resultado. Con pocas etiquetas no se concluye nada.

Se compara contra lo que el contrato prometió (métricas de prueba al entrenar):
- PR-AUC: ¿ordena igual de bien?
- Brecha de calibración (puntaje promedio − tasa real): ¿sus probabilidades siguen siendo
  fieles? Es la primera en romperse ante un concept drift.
- Costo por ticket con el umbral vigente: ¿la decisión sigue siendo buena para el negocio?
"""

from dataclasses import dataclass

import numpy as np

from mlplatform.training.metrics import binary_classification_metrics
from mlplatform.training.thresholds import threshold_metrics

MIN_LABELS = 300


@dataclass(frozen=True)
class PerformanceTolerances:
    pr_auc_drop: float = 0.05  # caída máxima aceptada frente al contrato
    brier_increase: float = 0.02
    cost_increase: float = 0.05
    calibration_gap: float = 0.05  # |puntaje promedio − tasa real|


@dataclass(frozen=True)
class PerformanceCheck:
    name: str
    expected: float
    observed: float
    limit: str
    passed: bool


def live_metrics(
    y_true, scores, threshold: float, cost_fp: float, cost_fn: float
) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=int)
    scores = np.asarray(scores, dtype=float)
    decision = threshold_metrics(y_true, scores, threshold, cost_fp, cost_fn)
    return {
        **binary_classification_metrics(y_true, scores),
        "mean_score": float(scores.mean()),
        "calibration_gap": float(scores.mean() - y_true.mean()),
        "precision": decision["precision"],
        "recall": decision["recall"],
        "alert_rate": decision["alert_rate"],
        "cost_per_ticket": decision["cost_per_ticket"],
    }


def compare_to_contract(
    observed: dict[str, float],
    expected: dict[str, float],
    tolerances: PerformanceTolerances | None = None,
) -> list[PerformanceCheck]:
    tol = tolerances or PerformanceTolerances()
    checks = [
        PerformanceCheck(
            "pr_auc",
            expected["pr_auc"],
            observed["pr_auc"],
            f">= {expected['pr_auc'] - tol.pr_auc_drop:.3f}",
            observed["pr_auc"] >= expected["pr_auc"] - tol.pr_auc_drop,
        ),
        PerformanceCheck(
            "brier",
            expected["brier"],
            observed["brier"],
            f"<= {expected['brier'] + tol.brier_increase:.3f}",
            observed["brier"] <= expected["brier"] + tol.brier_increase,
        ),
        PerformanceCheck(
            "calibration_gap",
            0.0,
            observed["calibration_gap"],
            f"|gap| <= {tol.calibration_gap:.3f}",
            abs(observed["calibration_gap"]) <= tol.calibration_gap,
        ),
    ]
    if "cost_per_ticket" in expected:
        checks.append(
            PerformanceCheck(
                "cost_per_ticket",
                expected["cost_per_ticket"],
                observed["cost_per_ticket"],
                f"<= {expected['cost_per_ticket'] + tol.cost_increase:.3f}",
                observed["cost_per_ticket"] <= expected["cost_per_ticket"] + tol.cost_increase,
            )
        )
    return checks
