from datetime import date

import numpy as np
import pandas as pd
import pytest

from use_cases.sla_risk.simulate import validate_simulation
from use_cases.sla_risk.simulator import BUSINESS_TZ, DriftScenario, SimulationConfig, simulate


def test_same_seed_same_data(small_sim, small_config) -> None:
    again = simulate(small_config)

    pd.testing.assert_frame_equal(small_sim.tickets, again.tickets)
    pd.testing.assert_frame_equal(small_sim.events, again.events)


def test_different_seed_different_data(small_sim, small_config) -> None:
    other = simulate(SimulationConfig(days=small_config.days, seed=small_config.seed + 1))

    assert not small_sim.tickets["ticket_id"].isin(other.tickets["ticket_id"]).any()


def test_output_passes_quality_checks(small_sim) -> None:
    report = validate_simulation(small_sim)

    assert report.ok, report.issues


def test_breach_rate_is_plausible(small_sim) -> None:
    rate = small_sim.tickets["sla_breached"].dropna().astype(float).mean()

    assert 0.05 < rate < 0.35


def test_label_is_unknown_only_while_outcome_is_undetermined(small_sim) -> None:
    t = small_sim.tickets
    deadline = t["created_at"] + pd.to_timedelta(t["sla_hours"], unit="h")
    unknown = t["sla_breached"].isna()

    # Desconocido <=> ni resuelto ni vencido en el snapshot.
    expected_unknown = t["resolved_at"].isna() & (deadline > small_sim.as_of)
    assert (unknown == expected_unknown).all()
    # Vencido y sin resolver => incumplimiento seguro.
    assert t.loc[t["resolved_at"].isna() & (deadline <= small_sim.as_of), "sla_breached"].all()


def test_snapshot_does_not_contain_the_future() -> None:
    as_of = pd.Timestamp("2025-01-20 12:00", tz="America/Bogota")
    result = simulate(SimulationConfig(days=28, tickets_per_day=60, seed=3, as_of=as_of))

    for col in ["created_at", "first_response_at", "resolved_at", "closed_at"]:
        assert (result.tickets[col].dropna() <= as_of).all(), col
    assert (result.events["event_at"] <= as_of).all()


@pytest.mark.parametrize("n_rows", [400])
def test_queue_feature_is_point_in_time(small_sim, n_rows: int) -> None:
    """Recalcula open_tickets_in_queue por fuerza bruta usando solo el pasado de cada ticket.

    Un ticket j cuenta como abierto en el instante t_i si se creó antes que i y no estaba
    resuelto en t_i. Los tickets sin resolved_at en el snapshot siguen abiertos.
    """
    t = small_sim.tickets
    created = t["created_at"].to_numpy()
    resolved = t["resolved_at"].fillna(pd.Timestamp.max.tz_localize("UTC")).to_numpy()

    sample = np.linspace(0, len(t) - 1, n_rows).astype(int)
    expected = [int(((created < created[i]) & (resolved > created[i])).sum()) for i in sample]

    assert t["open_tickets_in_queue"].iloc[sample].tolist() == expected


def test_the_past_does_not_depend_on_the_future() -> None:
    """Simular más días no cambia los días ya simulados: el tiempo "avanza" en el mismo mundo."""
    short = simulate(SimulationConfig(days=30, tickets_per_day=40))
    longer = simulate(
        SimulationConfig(
            days=50, tickets_per_day=40, as_of=pd.Timestamp("2025-02-05", tz=BUSINESS_TZ)
        )
    )

    pd.testing.assert_frame_equal(short.tickets, longer.tickets)
    pd.testing.assert_frame_equal(short.events, longer.events)


def test_drift_only_changes_the_world_after_it_starts() -> None:
    base = SimulationConfig(days=60, tickets_per_day=80)
    drift_start = date(2025, 2, 5)
    drifted = simulate(
        SimulationConfig(days=60, tickets_per_day=80, drift=DriftScenario(drift_start, 60))
    ).tickets
    normal = simulate(base).tickets
    cut = pd.Timestamp(drift_start, tz=BUSINESS_TZ)

    before = normal["created_at"] < cut
    t0_columns = ["ticket_id", "created_at", "channel", "priority", "open_tickets_in_queue"]
    pd.testing.assert_frame_equal(drifted.loc[before, t0_columns], normal.loc[before, t0_columns])
    after = ~before
    assert (
        drifted.loc[after, "open_tickets_in_queue"].mean()
        > normal.loc[after, "open_tickets_in_queue"].mean() * 1.2
    )
    assert (
        drifted.loc[after, "sla_breached"].dropna().mean()
        > normal.loc[after, "sla_breached"].dropna().mean()
    )
