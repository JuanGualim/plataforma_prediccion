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
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

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
