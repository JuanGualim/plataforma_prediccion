import numpy as np
import pandas as pd

from use_cases.sla_risk.feast_export import build_tables
from use_cases.sla_risk.feature_experiment import paired_bootstrap, per_row_losses


def test_bootstrap_interval_contains_zero_for_identical_models() -> None:
    y = np.array([0, 1, 0, 0, 1, 0, 1, 0])
    scores = np.linspace(0.1, 0.8, 8)
    losses = per_row_losses(y, scores, 0.5)

    interval = paired_bootstrap(losses, losses, n_boot=200, seed=0)

    assert interval == {"brier": [0.0, 0.0], "cost_per_ticket": [0.0, 0.0]}


def test_per_row_cost_matches_the_cost_definition() -> None:
    y = np.array([1, 0, 1, 0])
    losses = per_row_losses(y, np.array([0.9, 0.9, 0.1, 0.1]), 0.5)

    assert losses["cost_per_ticket"].tolist() == [0, 1, 5, 0]  # TP, FP, FN, TN


def test_feast_export_hourly_values_match_the_floor_of_each_ticket(small_sim) -> None:
    tables = build_tables(small_sim.tickets)

    expected = tables["expected"]
    operations = tables["operations_hourly"].set_index("event_timestamp")
    floor = pd.to_datetime(expected["created_at"]).dt.tz_convert("UTC").dt.floor("h")
    from_table = operations.loc[floor, "arrivals_24h"].to_numpy()

    assert (from_table == expected["hourly_arrivals_24h"].to_numpy()).all()
    assert len(tables["category_hourly"]) == 5 * len(operations)
