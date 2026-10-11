import json

import joblib
import pytest

from use_cases.sla_risk.dataset import build_splits, default_cutoffs
from use_cases.sla_risk.train import TrainingConfig, save_run, train

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


def test_saved_run_reproduces_predictions(tmp_path, small_sim, outcome) -> None:
    run_dir = save_run(outcome, tmp_path)

    artifact = joblib.load(run_dir / "model.joblib")
    splits = build_splits(small_sim.tickets, *default_cutoffs(small_sim.tickets, 7, 7))
    X = splits.test.X

    assert artifact["threshold"] == outcome.threshold
    assert (artifact["model"].predict_proba(X)[:, 1] == outcome.model.predict_proba(X)[:, 1]).all()
    assert json.loads((run_dir / "report.json").read_text())["use_case"] == "sla_risk"
