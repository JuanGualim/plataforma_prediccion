"""Conversión de probabilidades en decisiones: elegir el umbral.

El modelo entrega una probabilidad; el negocio necesita un sí/no ("¿escalo este ticket?").
El umbral se elige minimizando el COSTO ESPERADO de los errores en el conjunto de validación:

    costo = cost_fp × falsas_alarmas + cost_fn × casos_no_detectados

Referencia teórica: si las probabilidades están bien calibradas, el umbral óptimo es
cost_fp / (cost_fp + cost_fn). Se reporta junto al umbral empírico como chequeo de cordura.
"""

import numpy as np
import pandas as pd

DEFAULT_GRID = np.round(np.arange(0.01, 1.0, 0.01), 2)


def threshold_metrics(
    y_true, y_score, threshold: float, cost_fp: float = 1.0, cost_fn: float = 1.0
) -> dict[str, float]:
    """Confusion counts and derived metrics for the rule `alert if score >= threshold`."""
    y_true = np.asarray(y_true, dtype=int)
    alert = np.asarray(y_score, dtype=float) >= threshold
    tp = int(np.sum(alert & (y_true == 1)))
    fp = int(np.sum(alert & (y_true == 0)))
    fn = int(np.sum(~alert & (y_true == 1)))
    tn = int(np.sum(~alert & (y_true == 0)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "alert_rate": float(alert.mean()),
        "cost_per_ticket": (cost_fp * fp + cost_fn * fn) / len(y_true),
    }


def threshold_curve(
    y_true, y_score, cost_fp: float, cost_fn: float, grid: np.ndarray = DEFAULT_GRID
) -> pd.DataFrame:
    return pd.DataFrame([threshold_metrics(y_true, y_score, t, cost_fp, cost_fn) for t in grid])


def select_threshold_min_cost(
    y_true, y_score, cost_fp: float, cost_fn: float, grid: np.ndarray = DEFAULT_GRID
) -> float:
    """Threshold in `grid` with the lowest expected cost (ties -> the higher threshold).

    Ante un empate se prefiere el umbral más alto: mismo costo con menos alertas.
    """
    curve = threshold_curve(y_true, y_score, cost_fp, cost_fn, grid)
    best = curve["cost_per_ticket"].min()
    return float(curve.loc[np.isclose(curve["cost_per_ticket"], best), "threshold"].max())


def calibrated_optimal_threshold(cost_fp: float, cost_fn: float) -> float:
    return cost_fp / (cost_fp + cost_fn)
