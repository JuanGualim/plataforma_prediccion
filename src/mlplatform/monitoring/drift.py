"""Monitoreo de datos y de predicciones: ¿lo que llega se parece a lo que el modelo conoció?

1. Al entrenar se guarda un **perfil de referencia** (`ReferenceProfile`): la distribución de cada
   entrada y del puntaje en un periodo que el modelo no usó para aprender (la ventana de prueba),
   más las categorías que vio en entrenamiento.
2. En producción se compara la distribución actual con ese perfil usando el **PSI**
   (Population Stability Index):

       PSI = Σ (actual_i − esperado_i) · ln(actual_i / esperado_i)

   sobre las mismas "cajas" (categorías o rangos de valores). Umbrales habituales:
   < 0,1 estable · 0,1–0,25 cambio moderado · ≥ 0,25 cambio importante.
3. Una categoría nunca vista es una alerta por sí misma, aunque sea poco frecuente.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pydantic import BaseModel

PSI_WARNING = 0.10
PSI_ALERT = 0.25
MIN_ROWS = 200  # con menos filas el PSI es demasiado ruidoso para concluir algo
_EPS = 1e-4  # evita log(0) cuando una caja queda vacía


class CategoricalProfile(BaseModel):
    proportions: dict[str, float]
    known: list[str]  # categorías vistas en entrenamiento


class NumericProfile(BaseModel):
    edges: list[float]  # cortes interiores (deciles de la referencia)
    proportions: list[float]  # len(edges) + 1 cajas
    mean: float


class ReferenceProfile(BaseModel):
    description: str
    n_rows: int
    categorical: dict[str, CategoricalProfile]
    numeric: dict[str, NumericProfile]
    score: NumericProfile


def numeric_profile(values: Sequence[float], n_bins: int = 10) -> NumericProfile:
    values = np.asarray(values, dtype=float)
    quantiles = np.quantile(values, np.linspace(0, 1, n_bins + 1)[1:-1])
    edges = np.unique(quantiles).tolist()  # variables discretas producen cortes repetidos
    return NumericProfile(
        edges=edges,
        proportions=_bin_proportions(values, edges).tolist(),
        mean=float(values.mean()),
    )


def categorical_profile(values: Sequence, known: Sequence | None = None) -> CategoricalProfile:
    counts = pd.Series(values).astype(str).value_counts(normalize=True)
    known_values = sorted(map(str, known)) if known is not None else sorted(counts.index)
    return CategoricalProfile(proportions=counts.to_dict(), known=known_values)


def build_profile(
    frame: pd.DataFrame,
    scores: Sequence[float],
    categorical: Sequence[str],
    numeric: Sequence[str],
    known_categories: dict[str, Sequence] | None = None,
    description: str = "",
) -> ReferenceProfile:
    known_categories = known_categories or {}
    return ReferenceProfile(
        description=description,
        n_rows=len(frame),
        categorical={
            c: categorical_profile(frame[c], known_categories.get(c)) for c in categorical
        },
        numeric={c: numeric_profile(frame[c]) for c in numeric},
        score=numeric_profile(scores),
    )


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    e = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), _EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def _bin_proportions(values: np.ndarray, edges: Sequence[float]) -> np.ndarray:
    bins = np.concatenate([[-np.inf], edges, [np.inf]])
    counts, _ = np.histogram(values, bins=bins)
    return counts / max(len(values), 1)


@dataclass(frozen=True)
class FeatureDrift:
    name: str
    kind: str  # categorical | numeric | score
    n: int
    psi: float
    status: str  # ok | warning | alert | insufficient_data
    new_categories: list[str] = field(default_factory=list)
    reference_mean: float | None = None
    current_mean: float | None = None


@dataclass(frozen=True)
class DriftReport:
    n: int
    features: list[FeatureDrift]
    score: FeatureDrift

    def worst(self) -> str:
        order = ["ok", "insufficient_data", "warning", "alert"]
        statuses = [f.status for f in [*self.features, self.score]]
        return max(statuses, key=order.index)


def _status(value: float, n: int, new_categories: list[str] | None = None) -> str:
    if n < MIN_ROWS:
        return "insufficient_data"
    if new_categories or value >= PSI_ALERT:
        return "alert"
    return "warning" if value >= PSI_WARNING else "ok"


def _numeric_drift(name: str, kind: str, ref: NumericProfile, values: np.ndarray) -> FeatureDrift:
    current = _bin_proportions(values, ref.edges)
    value = psi(ref.proportions, current)
    return FeatureDrift(
        name=name,
        kind=kind,
        n=len(values),
        psi=value,
        status=_status(value, len(values)),
        reference_mean=ref.mean,
        current_mean=float(values.mean()) if len(values) else None,
    )


def compare(profile: ReferenceProfile, frame: pd.DataFrame, scores: Sequence[float]) -> DriftReport:
    """Compare a window of production inputs and scores against the reference profile."""
    n = len(frame)
    features = []
    for name, ref in profile.categorical.items():
        current = frame[name].astype(str).value_counts(normalize=True).to_dict()
        categories = sorted(set(ref.proportions) | set(current))
        value = psi(
            [ref.proportions.get(c, 0.0) for c in categories],
            [current.get(c, 0.0) for c in categories],
        )
        new = sorted(set(current) - set(ref.known))
        features.append(FeatureDrift(name, "categorical", n, value, _status(value, n, new), new))
    for name, ref in profile.numeric.items():
        features.append(_numeric_drift(name, "numeric", ref, frame[name].to_numpy(dtype=float)))
    score = _numeric_drift("score", "score", profile.score, np.asarray(scores, dtype=float))
    return DriftReport(n=n, features=features, score=score)
