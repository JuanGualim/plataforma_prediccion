"""Las variables de contexto no miran el futuro: se comprueba "viajando en el tiempo".

El simulador puede mostrar el mismo mundo tal como se conocía en cualquier instante (`as_of`).
Calcular las variables en T con la historia completa debe dar lo mismo que calcularlas con la
historia que existía en T. Si alguna usara un dato posterior a T, las dos versiones diferirían.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from mlplatform.features.point_in_time import EventStream
from use_cases.sla_risk.context_features import (
    CONTEXT_FEATURES,
    context_features,
    outcome_known_at,
)
from use_cases.sla_risk.simulator import simulate


@pytest.mark.parametrize("day", [9, 16, 23])
def test_features_at_t_only_use_what_was_known_at_t(small_sim, small_config, day) -> None:
    moment = small_sim.tickets["created_at"].min().normalize() + pd.Timedelta(
        days=day, hours=10, minutes=17, seconds=30.5
    )
    request = pd.DataFrame(
        {
            "created_at": [moment] * 5,
            "category": ["billing", "network", "account", "hardware", "software"],
        }
    )
    known_then = simulate(replace(small_config, as_of=moment)).tickets

    with_full_history = context_features(small_sim.tickets, request)
    with_history_at_t = context_features(known_then, request)

    pd.testing.assert_frame_equal(with_full_history, with_history_at_t)
    assert (with_full_history["arrivals_24h"] > 0).all()


def test_outcome_known_at_follows_the_label_semantics(small_sim) -> None:
    tickets = small_sim.tickets
    known = outcome_known_at(tickets)
    deadline = tickets["created_at"] + pd.to_timedelta(tickets["sla_hours"], unit="h")
    breached = tickets["sla_breached"]

    assert known[breached.isna()].isna().all()
    late = breached.eq(True).fillna(False)
    assert (known[late] == deadline[late]).all()
    on_time = breached.eq(False).fillna(False)
    assert (known[on_time] == tickets.loc[on_time, "resolved_at"]).all()
    assert (known.dropna() >= tickets.loc[known.notna(), "created_at"]).all()


def test_training_rows_do_not_count_themselves(small_sim) -> None:
    tickets = small_sim.tickets.sort_values("created_at").head(5)

    features = context_features(tickets, tickets)

    assert features["arrivals_24h"].tolist() == [0, 1, 2, 3, 4]
    assert list(features.columns) == CONTEXT_FEATURES


def test_time_travel_check_catches_a_leaky_definition(small_sim, small_config) -> None:
    """Control: fechar el resultado al CREAR el ticket (no al saberse) es una fuga clásica."""
    moment = small_sim.tickets["created_at"].min().normalize() + pd.Timedelta(days=16, hours=10)
    known_then = simulate(replace(small_config, as_of=moment)).tickets

    def leaky_rate(tickets: pd.DataFrame) -> float:
        events = EventStream.from_series(tickets["created_at"], tickets["sla_breached"])
        known = events.values[~np.isnan(events.values)]
        return float(known.mean())

    assert leaky_rate(small_sim.tickets[small_sim.tickets["created_at"] < moment]) != leaky_rate(
        known_then[known_then["created_at"] < moment]
    )
