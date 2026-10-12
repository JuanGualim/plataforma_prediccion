import json

import pytest

from use_cases.sla_risk.train import TrainingConfig, train

SMALL_TRAINING = TrainingConfig(validation_days=7, test_days=7, permutation_repeats=2)


@pytest.fixture(scope="module")
def outcome(small_sim):
    return train(small_sim.tickets, SMALL_TRAINING)


def test_report_is_complete_and_json_serializable(outcome) -> None:
    report = outcome.report

    for key in ("data", "candidates_validation", "selected", "threshold", "test", "lineage"):
        assert key in report
    assert report["selected"]["name"] in {c["name"] for c in report["candidates_validation"]}
    assert 0 < report["threshold"]["value"] < 1
    json.dumps(report, allow_nan=False)  # JSON estricto: sin NaN


def test_threshold_is_chosen_on_validation_not_test(outcome) -> None:
    """El umbral reportado es el que minimiza el costo en VALIDACIÓN."""
    report = outcome.report
    validation_cost = report["threshold"]["validation_decision"]["cost_per_ticket"]
    never_alert_cost_validation = (
        report["config"]["cost_false_negative"] * report["data"]["prevalence"]["validation"]
    )

    assert report["threshold"]["validation_decision"]["threshold"] == report["threshold"]["value"]
    assert validation_cost <= never_alert_cost_validation


def test_training_is_reproducible(small_sim, outcome) -> None:
    again = train(small_sim.tickets, SMALL_TRAINING)

    def stable(report: dict) -> dict:
        candidates = [
            {k: v for k, v in c.items() if k != "fit_seconds"}
            for c in report["candidates_validation"]
        ]
        return {**report["test"], "candidates": candidates, "threshold": report["threshold"]}

    assert stable(again.report) == stable(outcome.report)


def test_candidates_can_be_restricted_by_name(small_sim) -> None:
    config = TrainingConfig(
        validation_days=7, test_days=7, permutation_repeats=1, candidate_names=("logreg",)
    )

    outcome = train(small_sim.tickets, config)

    assert [c["name"] for c in outcome.report["candidates_validation"]] == ["logreg"]


def test_unknown_candidate_name_fails_fast(small_sim) -> None:
    config = TrainingConfig(validation_days=7, test_days=7, candidate_names=("nope",))
    with pytest.raises(ValueError, match="no candidate"):
        train(small_sim.tickets, config)


def test_train_days_limits_history_before_the_validation_cutoff(small_sim) -> None:
    config = TrainingConfig(
        validation_days=7,
        test_days=7,
        permutation_repeats=1,
        candidate_names=("logreg",),
        train_days=7,
    )

    report = train(small_sim.tickets, config).report

    full = train(
        small_sim.tickets,
        TrainingConfig(
            validation_days=7, test_days=7, permutation_repeats=1, candidate_names=("logreg",)
        ),
    ).report
    assert report["data"]["n"]["train"] < full["data"]["n"]["train"]
    assert report["data"]["n"]["test"] == full["data"]["n"]["test"]
