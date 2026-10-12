"""Qué se vigila del modelo de SLA y cómo se arma la tabla para compararla.

Las mismas funciones construyen el perfil de referencia al entrenar y la tabla de producción al
monitorear: si se calcularan distinto, se vería un "drift" que solo es una diferencia de código.
"""

import pandas as pd

from mlplatform.monitoring.drift import ReferenceProfile, build_profile
from use_cases.sla_risk.simulator import BUSINESS_TZ

MONITORED_CATEGORICAL = ["channel", "category", "priority", "customer_tier", "product"]
MONITORED_NUMERIC = ["sla_hours", "open_tickets_in_queue", "created_hour"]
REFERENCE_PROFILE_ARTIFACT = "reference_profile.json"


def monitoring_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """Monitored columns from raw rows (training rows or logged prediction inputs)."""
    frame = rows[MONITORED_CATEGORICAL + ["sla_hours", "open_tickets_in_queue"]].copy()
    created = pd.to_datetime(rows["created_at"], utc=True).dt.tz_convert(BUSINESS_TZ)
    frame["created_hour"] = created.dt.hour
    return frame


def reference_profile(
    reference_rows: pd.DataFrame, reference_scores, training_rows: pd.DataFrame, description: str
) -> ReferenceProfile:
    """Distributions of the reference window; known categories come from the training rows."""
    return build_profile(
        monitoring_frame(reference_rows),
        scores=reference_scores,
        categorical=MONITORED_CATEGORICAL,
        numeric=MONITORED_NUMERIC,
        known_categories={c: training_rows[c].astype(str).unique() for c in MONITORED_CATEGORICAL},
        description=description,
    )
