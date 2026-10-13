"""Variables point-in-time (T0*): agregados del pasado calculados en el instante de cada predicción.

Una variable T0* resume lo que ocurrió **antes** de T0: "tickets creados en las últimas 24 h",
"tasa de incumplimiento de la última semana". Es fácil calcularlas mal: con la tabla completa
a mano, basta un `<=` en vez de un `<` o un evento fechado al cerrar el ticket para que el
modelo vea el futuro en el entrenamiento (y no lo tenga en producción).

Reglas de este módulo:
1. Un evento cuenta en el instante `t` solo si ocurrió **estrictamente antes** de `t`.
2. Cada evento lleva la fecha en que **se supo**, no la fecha a la que se refiere. Por ejemplo,
   un incumplimiento se sabe al vencer el plazo, no al crear el ticket.
3. La misma función sirve para entrenar (muchos instantes del pasado) y para servir (un
   instante: ahora). Una sola definición evita el *training/serving skew*.

Implementación: eventos ordenados + sumas acumuladas + búsqueda binaria. Cuesta
O((n + m) log n) para n eventos y m instantes, sin bucles en Python.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

_MICROSECOND = pd.Timedelta(microseconds=1)


def to_micros(times: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Timezone-aware timestamps -> int64 microseconds since the epoch (UTC)."""
    utc = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None)
    return utc.to_numpy(dtype="datetime64[us]").astype(np.int64)


def _window(window: pd.Timedelta) -> int:
    return int(window / _MICROSECOND)


@dataclass(frozen=True)
class EventStream:
    """Events sorted by the moment they became known, with a numeric value each."""

    times: np.ndarray  # int64 microseconds, ascending
    values: np.ndarray  # float64; 1.0 when only counting

    @classmethod
    def from_series(cls, known_at: pd.Series, values: pd.Series | None = None) -> "EventStream":
        """Events with an unknown moment (NaT) are dropped: they have not happened yet."""
        mask = known_at.notna().to_numpy()
        times = to_micros(known_at[mask])
        vals = np.ones(len(times)) if values is None else np.asarray(values[mask], dtype=float)
        order = np.argsort(times, kind="stable")
        return cls(times[order], vals[order])

    def _bounds(self, at: np.ndarray, window: pd.Timedelta) -> tuple[np.ndarray, np.ndarray]:
        # Ventana [t − w, t): incluye el borde viejo, excluye el instante t (regla 1).
        hi = np.searchsorted(self.times, at, side="left")
        lo = np.searchsorted(self.times, at - _window(window), side="left")
        return lo, hi

    def count(self, at: np.ndarray, window: pd.Timedelta) -> np.ndarray:
        lo, hi = self._bounds(at, window)
        return hi - lo

    def mean(
        self, at: np.ndarray, window: pd.Timedelta, min_events: int, default: float
    ) -> np.ndarray:
        """Mean of the values in the window; `default` when there are fewer than `min_events`."""
        lo, hi = self._bounds(at, window)
        cumulative = np.concatenate([[0.0], np.cumsum(self.values)])
        n = hi - lo
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = (cumulative[hi] - cumulative[lo]) / n
        return np.where(n >= min_events, mean, default)


def open_count(started_at: pd.Series, ended_at: pd.Series, at: np.ndarray) -> np.ndarray:
    """Items started before `t` and not yet ended before `t` (a queue length at each instant).

    `ended_at` puede ser NaT (todavía abierto). Que algo termine después de `t` no es mirar el
    futuro: en `t` solo se usa el hecho "todavía no había terminado".
    """
    started = np.sort(to_micros(started_at))
    ended = EventStream.from_series(ended_at).times
    return np.searchsorted(started, at, side="left") - np.searchsorted(ended, at, side="left")
