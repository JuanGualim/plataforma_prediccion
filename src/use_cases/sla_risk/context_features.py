"""Variables de contexto operativo del SLA (T0*), evaluadas en la fase 6 y NO usadas por el modelo.

Describen el estado del equipo de soporte en el instante T0, no el ticket:

- `arrivals_24h`: tickets creados en las 24 h previas (carga entrante).
- `breach_rate_7d`: fracción de incumplimientos entre los resultados que **se supieron** en los
  7 días previos. Es la única forma de que el modelo "vea" la capacidad del equipo, que no se
  observa directamente.
- `category_queue`: tickets abiertos de la misma categoría declarada (carga del equipo afín).

`breach_rate_7d` y `category_queue` se derivan de campos T+ (`resolved_at`, `sla_breached`).
Son válidas solo porque usan el hecho **conocido antes de T0**. Cuándo se sabe un resultado:
- resuelto dentro del plazo → se sabe al resolverse (no incumplió);
- incumplido → se sabe al vencer el plazo, aunque siga abierto.

El resultado de la fase 6 (docs/results/fase6_features_sla_risk.md) fue no incorporarlas: solo
aportan con drift y exigirían calcularlas en línea al servir.
"""

import numpy as np
import pandas as pd

from mlplatform.features.point_in_time import EventStream, open_count, to_micros

CONTEXT_FEATURES = ["arrivals_24h", "breach_rate_7d", "category_queue"]
BREACH_WINDOW = pd.Timedelta(days=7)
ARRIVALS_WINDOW = pd.Timedelta(hours=24)
MIN_OUTCOMES = 50  # con menos resultados en la ventana, la tasa es ruido
DEFAULT_BREACH_RATE = 0.15  # tasa histórica; solo al inicio de la serie


def outcome_known_at(tickets: pd.DataFrame) -> pd.Series:
    """Moment each SLA outcome became known (NaT if unknown in the snapshot)."""
    deadline = tickets["created_at"] + pd.to_timedelta(tickets["sla_hours"], unit="h")
    breached = tickets["sla_breached"]
    is_breach = breached.fillna(False).astype(bool)
    known = deadline.where(is_breach, tickets["resolved_at"])
    return known.where(breached.notna())


def context_features(tickets: pd.DataFrame, at: pd.DataFrame) -> pd.DataFrame:
    """Context of the support operation at each row of `at` (columns created_at, category).

    `tickets` es la historia (un snapshot de support.tickets); `at` son los instantes donde se
    evalúa: los mismos tickets al entrenar, o el ticket que se acaba de crear al servir.
    """
    at_us = to_micros(at["created_at"])
    arrivals = EventStream.from_series(tickets["created_at"])
    outcomes = EventStream.from_series(
        outcome_known_at(tickets), tickets["sla_breached"].astype(float)
    )
    queue = np.zeros(len(at), dtype=np.int64)
    for category, rows in tickets.groupby("category"):
        mask = (at["category"] == category).to_numpy()
        queue[mask] = open_count(rows["created_at"], rows["resolved_at"], at_us[mask])
    return pd.DataFrame(
        {
            "arrivals_24h": arrivals.count(at_us, ARRIVALS_WINDOW),
            "breach_rate_7d": outcomes.mean(
                at_us, BREACH_WINDOW, MIN_OUTCOMES, DEFAULT_BREACH_RATE
            ),
            "category_queue": queue,
        },
        index=at.index,
    )
