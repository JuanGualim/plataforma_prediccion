"""Métricas para clasificación binaria con clases desbalanceadas.

Todas trabajan sobre probabilidades (scores), no sobre decisiones sí/no: la elección
del umbral es una decisión aparte (fase 2).

- pr_auc (average precision): resume precisión vs. recall en todos los umbrales.
  Un modelo sin información obtiene ~prevalence, así que se compara contra ese número.
- roc_auc: probabilidad de que un positivo reciba más score que un negativo (0.5 = azar).
  Con clases muy desbalanceadas puede verse optimista; por eso la principal es pr_auc.
- brier: error cuadrático medio de la probabilidad (calibración + discriminación; menor es mejor).
- log_loss: castiga mucho las probabilidades muy seguras y equivocadas (menor es mejor).
"""

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from mlplatform.training.thresholds import threshold_metrics

_EPS = 1e-6


def binary_classification_metrics(y_true, y_score) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.clip(np.asarray(y_score, dtype=float), _EPS, 1 - _EPS)
    both_classes = len(np.unique(y_true)) == 2
    return {
        "n": int(len(y_true)),
        "prevalence": float(y_true.mean()),
        "pr_auc": float(average_precision_score(y_true, y_score)) if both_classes else np.nan,
        "roc_auc": float(roc_auc_score(y_true, y_score)) if both_classes else np.nan,
        "brier": float(brier_score_loss(y_true, y_score)),
        "log_loss": float(log_loss(y_true, y_score, labels=[0, 1])),
    }


def calibration_table(y_true, y_score, n_bins: int = 10) -> pd.DataFrame:
    """Compare predicted probability with the observed rate, by score decile.

    Un modelo calibrado tiene `mean_predicted ≈ observed_rate` en cada fila: cuando dice 30 %,
    ocurre ~30 % de las veces. Importa si la probabilidad se muestra a una persona o se usa
    para calcular costos.
    """
    frame = pd.DataFrame({"y": np.asarray(y_true, dtype=int), "score": np.asarray(y_score)})
    frame["bin"] = pd.qcut(frame["score"], q=n_bins, duplicates="drop")
    table = frame.groupby("bin", observed=True).agg(
        n=("y", "size"), mean_predicted=("score", "mean"), observed_rate=("y", "mean")
    )
    return table.reset_index(drop=True)


def metrics_by_segment(y_true, y_score, segments, threshold: float) -> pd.DataFrame:
    """Per-segment volume, prevalence and decision quality (e.g. by customer tier).

    Un buen promedio puede esconder un segmento donde el modelo falla; este corte es la base
    de la model card y del monitoreo por segmento.
    """
    frame = pd.DataFrame(
        {
            "y": np.asarray(y_true, dtype=int),
            "score": np.asarray(y_score),
            "segment": np.asarray(segments),
        }
    )
    rows = []
    for segment, group in frame.groupby("segment", observed=True):
        decision = threshold_metrics(group["y"], group["score"], threshold)
        both_classes = group["y"].nunique() == 2
        rows.append(
            {
                "segment": segment,
                "n": len(group),
                "prevalence": group["y"].mean(),
                "mean_score": group["score"].mean(),
                "pr_auc": average_precision_score(group["y"], group["score"])
                if both_classes
                else np.nan,
                "precision": decision["precision"],
                "recall": decision["recall"],
                "alert_rate": decision["alert_rate"],
            }
        )
    return pd.DataFrame(rows)
