"""Transformación de columnas crudas (FEATURES) a la matriz numérica que ve el modelo.

Todo vive DENTRO del pipeline de scikit-learn, que se guarda junto con el modelo. Así el
serving (fase 4) aplica exactamente la misma transformación que el entrenamiento y se evita
el "training/serving skew": que el modelo reciba en producción datos preparados de otra forma.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from use_cases.sla_risk.simulator import BUSINESS_TZ

CATEGORICAL = ["channel", "category", "priority", "customer_tier", "product"]
NUMERIC = ["sla_hours", "open_tickets_in_queue"]
TIME_SOURCE = ["created_at"]
TIME_FEATURES = ["hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "is_weekend", "is_off_hours"]


def time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive hour/weekday features from created_at in the support team's local time.

    Solo se usa la hora y el día de la semana, nunca la fecha absoluta: un modelo que aprende
    "en marzo hubo más incumplimientos" no sirve para predecir abril.
    Hora y día se codifican como seno/coseno para que 23 h y 0 h queden "cerca" (son cíclicos).
    """
    local = df["created_at"].dt.tz_convert(BUSINESS_TZ)
    hour = local.dt.hour + local.dt.minute / 60
    weekday = local.dt.weekday
    is_weekend = weekday >= 5
    return pd.DataFrame(
        {
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "weekday_sin": np.sin(2 * np.pi * weekday / 7),
            "weekday_cos": np.cos(2 * np.pi * weekday / 7),
            "is_weekend": is_weekend.astype(int),
            "is_off_hours": (is_weekend | (hour < 8) | (hour >= 18)).astype(int),
        },
        index=df.index,
    )


def _time_feature_names(transformer, input_features) -> list[str]:
    # Función con nombre (no lambda): el pipeline debe poder guardarse con joblib.
    return TIME_FEATURES


def build_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    """One-hot for categories, optional scaling for numbers, derived time features.

    `handle_unknown="ignore"`: una categoría nunca vista (p. ej. un canal nuevo) no rompe la
    predicción; se codifica como "ninguna conocida". Detectarla es tarea del monitoreo de datos.
    """
    return ColumnTransformer(
        [
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL,
            ),
            ("numeric", StandardScaler() if scale_numeric else "passthrough", NUMERIC),
            (
                "time",
                FunctionTransformer(time_features, feature_names_out=_time_feature_names),
                TIME_SOURCE,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


# Funciones propias que viajan dentro del modelo guardado. skops (formato seguro de MLflow)
# se niega a cargar código no declarado; esta lista blanca lo autoriza de forma explícita.
SKOPS_TRUSTED_TYPES = [
    f"{__name__}.{time_features.__name__}",
    f"{__name__}.{_time_feature_names.__name__}",
]
