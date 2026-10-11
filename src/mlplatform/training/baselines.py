"""Modelos de referencia (baselines) que cualquier modelo real debe superar.

Siguen la interfaz de scikit-learn (fit / predict_proba) para compararse con los modelos
de la fase 2 usando exactamente el mismo código de evaluación.
"""

from collections.abc import Sequence
from typing import Self

import numpy as np
import pandas as pd


class GroupRateClassifier:
    """Predict the historical positive rate of the row's group (e.g. priority x tier).

    Es una "regla de experto" automatizada: "los tickets críticos de clientes enterprise
    incumplen el X % de las veces". Las tasas se suavizan hacia la tasa global para que un
    grupo con muy pocos ejemplos no reciba una probabilidad extrema (2 de 2 = 100 %).
    Los grupos no vistos en entrenamiento reciben la tasa global.
    """

    def __init__(self, group_cols: Sequence[str], smoothing: float = 20.0) -> None:
        if not group_cols:
            raise ValueError("group_cols must not be empty (use DummyClassifier for a prior)")
        self.group_cols = list(group_cols)
        self.smoothing = smoothing

    def fit(self, X: pd.DataFrame, y) -> Self:
        y = np.asarray(y, dtype=float)
        self.global_rate_ = float(y.mean())
        stats = (
            X[self.group_cols]
            .assign(_y=y)
            .groupby(self.group_cols, observed=True)["_y"]
            .agg(["sum", "count"])
        )
        rates = (stats["sum"] + self.smoothing * self.global_rate_) / (
            stats["count"] + self.smoothing
        )
        self.rates_ = rates.rename("_rate").reset_index()
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        merged = X[self.group_cols].merge(self.rates_, how="left", on=self.group_cols)
        positive = merged["_rate"].fillna(self.global_rate_).to_numpy(dtype=float)
        return np.column_stack([1 - positive, positive])
