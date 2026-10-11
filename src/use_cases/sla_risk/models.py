"""Modelos candidatos para el riesgo de SLA.

- logreg: regresión logística. Lineal, rápida e interpretable (cada coeficiente se lee).
- logreg_balanced: igual, pero con `class_weight="balanced"`: da más peso a la clase rara.
  Suele ordenar los tickets parecido, pero infla las probabilidades (peor calibración).
  Está para mostrar ese efecto; el desbalance se maneja con el umbral, no con pesos.
- hgb_*: gradient boosting por histogramas. Captura interacciones (p. ej. prioridad × nivel ×
  carga) que el modelo lineal no ve, a cambio de ser menos interpretable.
"""

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from mlplatform.training.selection import Candidate
from use_cases.sla_risk.features import build_preprocessor

LINEAR, BOOSTING = 1, 2  # complejidad relativa (desempate de la selección)


def build_candidates(random_state: int = 42) -> list[Candidate]:
    def pipeline(model, scale_numeric: bool) -> Pipeline:
        return Pipeline(
            [("preprocess", build_preprocessor(scale_numeric)), ("model", model)]
        ).set_output(transform="pandas")

    candidates = [
        Candidate("logreg", pipeline(LogisticRegression(max_iter=2000), True), LINEAR),
        Candidate(
            "logreg_balanced",
            pipeline(LogisticRegression(max_iter=2000, class_weight="balanced"), True),
            LINEAR,
        ),
    ]
    for learning_rate in (0.05, 0.1):
        for max_leaf_nodes in (15, 31):
            model = HistGradientBoostingClassifier(
                learning_rate=learning_rate,
                max_leaf_nodes=max_leaf_nodes,
                max_iter=200,
                l2_regularization=1.0,
                early_stopping=False,  # sin partición aleatoria interna: reproducible y temporal
                random_state=random_state,
            )
            name = f"hgb_lr{learning_rate}_leaves{max_leaf_nodes}"
            candidates.append(Candidate(name, pipeline(model, False), BOOSTING))
    return candidates
