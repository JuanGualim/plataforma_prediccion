"""Simulador de tickets de soporte: el "mundo" del que aprende el modelo de SLA.

Las reglas están documentadas en docs/simulator.md.

Reproducibilidad: cada día usa su propio generador aleatorio, con semilla `[seed, día]`. Así
el pasado no depende del futuro: simular 270 días produce exactamente los mismos primeros
210 días que simular 210. Es lo que permite simular "el paso del tiempo" en un mismo mundo.

Internamente el tiempo se maneja en segundos enteros desde el inicio de la simulación,
para que las comparaciones "antes/después" sean exactas (sin errores de redondeo).
"""

import heapq
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from use_cases.sla_risk.fields import (
    CATEGORIES,
    CHANNELS,
    GROUPS,
    PRIORITIES,
    PRODUCTS,
    TIERS,
)

BUSINESS_TZ = "America/Bogota"  # zona horaria del área de soporte (sin horario de verano)
HOUR = 3600
DAY = 24 * HOUR

# --- Llegada de tickets ---------------------------------------------------------------------
WEEKDAY_FACTOR = np.array([1.25, 1.10, 1.00, 1.00, 0.95, 0.45, 0.30])  # lunes..domingo
HOURLY_PROFILE = np.array(
    [1, 1, 1, 1, 1, 2, 4, 7, 10, 12, 12, 11, 8, 9, 11, 11, 10, 8, 6, 4, 3, 2, 2, 1], dtype=float
)
CATEGORY_WEIGHTS = np.array([0.25, 0.25, 0.20, 0.10, 0.20])  # orden de CATEGORIES
PRIORITY_WEIGHTS_BY_CATEGORY = np.array(  # filas: CATEGORIES; columnas: PRIORITIES
    [
        [0.45, 0.40, 0.12, 0.03],  # billing
        [0.20, 0.40, 0.28, 0.12],  # network
        [0.40, 0.40, 0.15, 0.05],  # account
        [0.25, 0.40, 0.25, 0.10],  # hardware
        [0.35, 0.40, 0.18, 0.07],  # software
    ]
)
TIER_WEIGHTS = np.array([0.60, 0.30, 0.10])
PRODUCT_WEIGHTS = np.array([0.30, 0.20, 0.20, 0.15, 0.15])
GROUP_BY_CATEGORY = np.array(GROUPS)  # billing->billing_team, network->network_team, ...

# --- SLA comprometido (horas): filas TIERS, columnas PRIORITIES ------------------------------
SLA_HOURS = np.array(
    [
        [72, 48, 24, 8],  # basic
        [48, 24, 12, 6],  # business
        [24, 12, 8, 4],  # enterprise
    ]
)

# --- Tiempo de resolución: mediana base por prioridad y multiplicadores ----------------------
MEDIAN_HOURS_BY_PRIORITY = np.array([24.0, 11.0, 5.0, 2.0])
CATEGORY_COMPLEXITY = np.array([0.8, 1.3, 0.7, 1.6, 1.1])
CHANNEL_SPEED = np.array([1.15, 0.85, 0.80, 1.00])  # email, chat, phone, portal
TIER_SPEED = np.array([1.00, 0.85, 0.70])
OFF_HOURS_FACTOR = np.array([1.6, 1.6, 1.4, 1.1])  # por prioridad: lo crítico casi no espera
MISROUTE_FACTOR = 1.5
REASSIGNMENT_FACTOR = 1.25  # cada reasignación alarga la resolución
# Efecto de la carga: cola por encima de la capacidad -> resoluciones más lentas, y viceversa.
# Es un ciclo de retroalimentación (más lentitud -> más cola -> más lentitud). Con elasticidad
# alta o capacidad baja la cola colapsa (ver docs/simulator.md); los límites lo mantienen estable.
LOAD_ELASTICITY = 0.5
LOAD_BOUNDS = (-0.5, 1.0)  # rango permitido de (cola / capacidad - 1)
NOISE_SIGMA = 0.6  # variabilidad no explicable (log-normal)
FIRST_RESPONSE_MEAN_HOURS = np.array([4.0, 2.0, 0.75, 0.25])

SUBJECTS = {
    "billing": ["Cobro duplicado", "No llegó mi factura", "Valor incorrecto en la factura"],
    "network": ["Sin conexión a internet", "Internet muy lento", "Cortes intermitentes"],
    "account": ["No puedo iniciar sesión", "Cambiar titular de la cuenta", "Bloqueo de cuenta"],
    "hardware": ["Router no enciende", "Luz roja en el equipo", "Equipo dañado"],
    "software": ["La app se cierra sola", "Error al pagar en el portal", "No carga la página"],
}
DESCRIPTIONS = {
    "billing": [
        "Me cobraron dos veces el mismo mes y necesito la devolución.",
        "La factura de este mes trae un valor mayor al de mi plan.",
        "No he recibido la factura en mi correo y se vence pronto.",
    ],
    "network": [
        "Desde ayer no tengo internet en ninguna parte de la casa.",
        "La velocidad es mucho menor a la contratada en las noches.",
        "La conexión se cae cada pocos minutos y vuelve sola.",
    ],
    "account": [
        "Intento entrar a mi cuenta y dice que la contraseña es incorrecta.",
        "Quiero cambiar el titular del servicio a nombre de mi esposa.",
        "Mi cuenta aparece bloqueada después de varios intentos.",
    ],
    "hardware": [
        "El router no prende aunque está conectado a la corriente.",
        "El equipo muestra una luz roja fija y no hay servicio.",
        "El módem se calienta mucho y se reinicia solo.",
    ],
    "software": [
        "La aplicación móvil se cierra al abrir la sección de pagos.",
        "Al pagar en el portal sale un error y no se completa la transacción.",
        "La página de autogestión se queda cargando y nunca abre.",
    ],
}
PII_PROBABILITY = 0.2  # fracción de descripciones con datos personales (ficticios)


@dataclass(frozen=True)
class DriftScenario:
    """A change in the world from `start` on (phase 5). Nothing before `start` changes."""

    start: date
    queue_capacity: float | None = None  # p. ej. el equipo pierde personal


@dataclass(frozen=True)
class SimulationConfig:
    start: date = date(2025, 1, 6)
    days: int = 180
    tickets_per_day: float = 120.0
    seed: int = 42
    channel_weights: tuple[float, ...] = (0.40, 0.25, 0.15, 0.20)  # orden de CHANNELS
    misroute_rate: float = 0.15  # el cliente elige mal la categoría
    queue_capacity: float = 110.0  # tickets abiertos que el equipo maneja sin degradarse
    # Momento del "snapshot": lo que se sabe en ese instante. None = fin del periodo simulado.
    as_of: datetime | None = None
    drift: DriftScenario | None = None


@dataclass(frozen=True)
class SimulationResult:
    tickets: pd.DataFrame
    events: pd.DataFrame
    as_of: pd.Timestamp
    config: SimulationConfig = field(repr=False)


def simulate(config: SimulationConfig | None = None) -> SimulationResult:
    config = config or SimulationConfig()
    start = pd.Timestamp(config.start, tz=BUSINESS_TZ)
    as_of_s = _as_of_seconds(config, start)

    days = [_draw_day(config, day) for day in range(config.days)]
    d = {key: np.concatenate([day[key] for day in days]) for key in days[0]}
    # Instantes únicos: dos tickets nunca se crean en el mismo segundo (orden sin ambigüedad).
    created_s = _strictly_increasing(d["created_s"])
    true_cat, priority, channel, tier = d["true_cat"], d["priority"], d["channel"], d["tier"]
    misrouted, reassignments = d["misrouted"], d["reassignments"]
    sla_hours = SLA_HOURS[tier, priority]

    local_hour = (created_s // HOUR) % 24
    weekday = (config.start.weekday() + created_s // DAY) % 7
    off_hours = (weekday >= 5) | (local_hour < 8) | (local_hour >= 18)

    # --- Dinámica posterior a T0 (el modelo NO la ve) ---
    base_hours = (
        MEDIAN_HOURS_BY_PRIORITY[priority]
        * CATEGORY_COMPLEXITY[true_cat]
        * CHANNEL_SPEED[channel]
        * TIER_SPEED[tier]
        * np.where(off_hours, OFF_HOURS_FACTOR[priority], 1.0)
        * np.where(misrouted, MISROUTE_FACTOR, 1.0)
        * REASSIGNMENT_FACTOR**reassignments
        * np.exp(NOISE_SIGMA * d["noise"])
    )
    assign_delay_s = d["assign_delay_s"] * np.where(off_hours, 4, 1)
    response_delay_s = (
        d["response_exp"] * FIRST_RESPONSE_MEAN_HOURS[priority] * HOUR * np.where(off_hours, 3, 1)
    ).astype(np.int64)
    min_duration_s = assign_delay_s + response_delay_s + 10 * 60

    capacity = np.full(len(created_s), config.queue_capacity, dtype=float)
    if config.drift is not None and config.drift.queue_capacity is not None:
        drift_s = (pd.Timestamp(config.drift.start, tz=BUSINESS_TZ) - start).total_seconds()
        capacity[created_s >= drift_s] = config.drift.queue_capacity

    open_in_queue, resolved_s = _run_queue(created_s, base_hours, min_duration_s, capacity)
    assigned_s = created_s + assign_delay_s
    first_response_s = assigned_s + response_delay_s
    closed_s = resolved_s + d["close_offset_s"]

    ticket_ids = np.array([str(uuid.UUID(bytes=row.tobytes(), version=4)) for row in d["id_bytes"]])
    subject, description = _texts(true_cat, d["text_picks"], d["has_pii"], d["contact"])

    # --- Snapshot: solo lo ocurrido hasta as_of ---
    events = _events(
        ticket_ids, created_s, assigned_s, first_response_s, resolved_s, closed_s,
        reassignments, as_of_s, start,
    )  # fmt: skip
    reassign_known = events.loc[events["event_type"] == "reassigned"].groupby("ticket_id").size()

    def ts(seconds: np.ndarray, known: np.ndarray | None = None) -> pd.Series:
        values = _timestamps(start, seconds)
        return values if known is None else values.where(known)

    resolved_known = resolved_s <= as_of_s
    closed_known = closed_s <= as_of_s
    deadline_s = created_s + sla_hours * HOUR
    breached = np.where(
        resolved_known,
        (resolved_s > deadline_s).astype(object),
        np.where(deadline_s <= as_of_s, True, pd.NA),
    )

    tickets = pd.DataFrame(
        {
            "ticket_id": ticket_ids,
            "created_at": ts(created_s),
            "channel": np.array(CHANNELS)[channel],
            "category": np.array(CATEGORIES)[d["declared_cat"]],
            "priority": np.array(PRIORITIES)[priority],
            "customer_tier": np.array(TIERS)[tier],
            "product": np.array(PRODUCTS)[d["product"]],
            "subject": subject,
            "description": description,
            "sla_hours": sla_hours.astype(int),
            "open_tickets_in_queue": open_in_queue,
            "assigned_group": pd.Series(GROUP_BY_CATEGORY[true_cat]).where(assigned_s <= as_of_s),
            "first_response_at": ts(first_response_s, first_response_s <= as_of_s),
            "reassignment_count": pd.Series(ticket_ids).map(reassign_known).fillna(0).astype(int),
            "resolved_at": ts(resolved_s, resolved_known),
            "closed_at": ts(closed_s, closed_known),
            "status": np.select([closed_known, resolved_known], ["closed", "resolved"], "open"),
            "sla_breached": pd.array(breached, dtype="boolean"),
        }
    )
    tickets = tickets[created_s <= as_of_s].reset_index(drop=True)
    return SimulationResult(tickets, events, start + pd.Timedelta(seconds=as_of_s), config)


def _as_of_seconds(config: SimulationConfig, start: pd.Timestamp) -> int:
    end_s = config.days * DAY
    if config.as_of is None:
        return end_s
    as_of = pd.Timestamp(config.as_of)
    as_of = as_of.tz_localize(BUSINESS_TZ) if as_of.tzinfo is None else as_of
    return min(int((as_of - start).total_seconds()), end_s)


def _draw_day(config: SimulationConfig, day: int) -> dict[str, np.ndarray]:
    """Every random draw of one day's tickets, sorted by creation time."""
    rng = np.random.default_rng([config.seed, day])
    weekday = (config.start.weekday() + day) % 7
    n = rng.poisson(config.tickets_per_day * WEEKDAY_FACTOR[weekday])
    hour = rng.choice(24, size=n, p=_normalize(HOURLY_PROFILE))
    created_s = (day * DAY + hour * HOUR + rng.integers(0, HOUR, size=n)).astype(np.int64)

    true_cat = rng.choice(len(CATEGORIES), size=n, p=CATEGORY_WEIGHTS)
    misrouted = rng.random(n) < config.misroute_rate
    shift = rng.integers(1, len(CATEGORIES), size=n)
    is_technical = np.isin(true_cat, [CATEGORIES.index("network"), CATEGORIES.index("hardware")])
    draws = {
        "created_s": created_s,
        "true_cat": true_cat,
        "misrouted": misrouted,
        "declared_cat": np.where(misrouted, (true_cat + shift) % len(CATEGORIES), true_cat),
        "priority": _choice_by_row(rng, PRIORITY_WEIGHTS_BY_CATEGORY[true_cat]),
        "channel": rng.choice(len(CHANNELS), size=n, p=_normalize(config.channel_weights)),
        "tier": rng.choice(len(TIERS), size=n, p=TIER_WEIGHTS),
        "product": rng.choice(len(PRODUCTS), size=n, p=PRODUCT_WEIGHTS),
        "reassignments": rng.poisson(0.25 + 1.2 * misrouted + 0.3 * is_technical),
        "noise": rng.standard_normal(n),
        "assign_delay_s": rng.integers(60, 30 * 60, size=n),
        "response_exp": rng.exponential(1.0, size=n),
        "close_offset_s": rng.integers(HOUR, 48 * HOUR, size=n),
        "id_bytes": np.frombuffer(rng.bytes(16 * n), dtype=np.uint8).reshape(n, 16),
        "text_picks": rng.integers(0, 3, size=(n, 2)),
        "has_pii": rng.random(n) < PII_PROBABILITY,
        "contact": rng.integers(1_000_000, 9_999_999, size=n),
    }
    order = np.argsort(created_s, kind="stable")
    return {key: value[order] for key, value in draws.items()}


def _strictly_increasing(values: np.ndarray) -> np.ndarray:
    """Smallest non-decreasing shift so that values[i] > values[i-1] (input must be sorted)."""
    offsets = np.arange(len(values))
    return np.maximum.accumulate(values - offsets) + offsets


def _run_queue(
    created_s: np.ndarray, base_hours: np.ndarray, min_duration_s: np.ndarray, capacity: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Process tickets in creation order, tracking how many are still open.

    `open_in_queue[i]` cuenta solo tickets creados ANTES de i y aún no resueltos en ese
    instante: es una feature point-in-time (T0*), calculada sin mirar el futuro.
    La carga, a su vez, alarga la resolución del ticket nuevo. `capacity` puede cambiar en el
    tiempo (escenario de drift).
    """
    n = len(created_s)
    open_in_queue = np.empty(n, dtype=np.int64)
    resolved_s = np.empty(n, dtype=np.int64)
    pending: list[int] = []  # min-heap con los instantes de resolución de tickets abiertos
    for i in range(n):
        now = created_s[i]
        while pending and pending[0] <= now:
            heapq.heappop(pending)
        open_in_queue[i] = len(pending)
        overload = min(max(len(pending) / capacity[i] - 1.0, LOAD_BOUNDS[0]), LOAD_BOUNDS[1])
        load_multiplier = math.exp(LOAD_ELASTICITY * overload)
        duration = max(int(base_hours[i] * load_multiplier * HOUR), int(min_duration_s[i]))
        resolved_s[i] = now + duration
        heapq.heappush(pending, int(resolved_s[i]))
    return open_in_queue, resolved_s


def _events(
    ticket_ids: np.ndarray,
    created_s: np.ndarray,
    assigned_s: np.ndarray,
    first_response_s: np.ndarray,
    resolved_s: np.ndarray,
    closed_s: np.ndarray,
    reassignments: np.ndarray,
    as_of_s: int,
    start: pd.Timestamp,
) -> pd.DataFrame:
    # Las reasignaciones se reparten de forma pareja entre la asignación y la resolución.
    idx = np.repeat(np.arange(len(ticket_ids)), reassignments)
    nth = np.concatenate([np.arange(1, r + 1) for r in reassignments]) if len(idx) else idx
    fraction = nth / (reassignments[idx] + 1)
    reassigned_s = assigned_s[idx] + (fraction * (resolved_s[idx] - assigned_s[idx])).astype(
        np.int64
    )
    every = np.arange(len(ticket_ids))
    zeros = np.zeros(len(ticket_ids), dtype=np.int64)
    parts = [
        ("created", every, zeros, created_s),
        ("assigned", every, zeros, assigned_s),
        ("first_response", every, zeros, first_response_s),
        ("reassigned", idx, nth, reassigned_s),
        ("resolved", every, zeros, resolved_s),
        ("closed", every, zeros, closed_s),
    ]
    frame = pd.concat(
        [
            pd.DataFrame({"ticket": i, "event_type": name, "nth": k, "at_s": s})
            for name, i, k, s in parts
        ],
        ignore_index=True,
    )
    frame = frame[frame["at_s"] <= as_of_s].sort_values(["at_s", "ticket"], kind="stable")
    ids = ticket_ids[frame["ticket"].to_numpy()]
    # Identificador determinista: el mismo evento tiene el mismo id en cualquier snapshot.
    event_ids = [
        str(uuid.uuid5(uuid.UUID(t), f"{kind}:{k}"))
        for t, kind, k in zip(ids, frame["event_type"], frame["nth"], strict=True)
    ]
    return pd.DataFrame(
        {
            "event_id": event_ids,
            "ticket_id": ids,
            "event_type": frame["event_type"].to_numpy(),
            "event_at": _timestamps(start, frame["at_s"].to_numpy()),
        }
    )


def _texts(
    true_cat: np.ndarray, picks: np.ndarray, has_pii: np.ndarray, contact: np.ndarray
) -> tuple[list[str], list[str]]:
    """Subject/description follow the TRUE category (useful for the routing model in phase 7)."""
    subjects, descriptions = [], []
    for i, cat_idx in enumerate(true_cat):
        cat = CATEGORIES[cat_idx]
        subjects.append(SUBJECTS[cat][picks[i, 0]])
        text = DESCRIPTIONS[cat][picks[i, 1]]
        if has_pii[
            i
        ]:  # datos personales ficticios: se usan en la fase 8 para probar el enmascarado
            text += (
                f" Pueden llamarme al 300{contact[i]}."
                if contact[i] % 2
                else f" Mi correo es cliente{contact[i]}@example.com."
            )
        descriptions.append(text)
    return subjects, descriptions


def _timestamps(start: pd.Timestamp, seconds: np.ndarray) -> pd.Series:
    """Seconds since start -> tz-aware timestamps in microseconds (PostgreSQL's precision)."""
    return pd.Series(start + pd.to_timedelta(seconds, unit="s")).dt.as_unit("us")


def _choice_by_row(rng: np.random.Generator, probabilities: np.ndarray) -> np.ndarray:
    """Draw one category index per row, each row with its own probability vector."""
    cumulative = probabilities.cumsum(axis=1)
    draws = rng.random(len(probabilities))[:, None]
    # El mínimo protege del caso en que la suma acumulada quede en 0.9999... por redondeo.
    return np.minimum((draws > cumulative).sum(axis=1), probabilities.shape[1] - 1)


def _normalize(weights) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    return weights / weights.sum()
