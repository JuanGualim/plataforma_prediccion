"""Comparación de modelos candidatos sobre el conjunto de validación.

Regla de selección: entre los candidatos cuya métrica está a menos de `tolerance` del mejor,
se elige el MÁS SIMPLE. Una mejora de 0,002 en PR-AUC no justifica un modelo más difícil de
explicar, operar y depurar.
"""

import time
from dataclasses import dataclass
from typing import Any

from sklearn.base import clone

from mlplatform.training.metrics import binary_classification_metrics


@dataclass(frozen=True)
class Candidate:
    name: str
    estimator: Any  # estimador o pipeline de scikit-learn SIN entrenar
    complexity: int  # menor = más simple; desempata la selección


@dataclass(frozen=True)
class CandidateResult:
    name: str
    complexity: int
    metrics: dict[str, float]
    fit_seconds: float
    model: Any  # estimador entrenado


def evaluate_candidates(
    candidates: list[Candidate], X_train, y_train, X_val, y_val
) -> list[CandidateResult]:
    results = []
    for candidate in candidates:
        model = clone(candidate.estimator)
        start = time.perf_counter()
        model.fit(X_train, y_train)
        elapsed = time.perf_counter() - start
        scores = model.predict_proba(X_val)[:, 1]
        results.append(
            CandidateResult(
                name=candidate.name,
                complexity=candidate.complexity,
                metrics=binary_classification_metrics(y_val, scores),
                fit_seconds=elapsed,
                model=model,
            )
        )
    return results


def select_candidate(
    results: list[CandidateResult], metric: str = "pr_auc", tolerance: float = 0.005
) -> CandidateResult:
    """Simplest candidate within `tolerance` of the best `metric` (higher is better)."""
    best = max(r.metrics[metric] for r in results)
    eligible = [r for r in results if r.metrics[metric] >= best - tolerance]
    return min(eligible, key=lambda r: (r.complexity, -r.metrics[metric]))
