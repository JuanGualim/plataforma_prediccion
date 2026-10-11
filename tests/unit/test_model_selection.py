import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from mlplatform.training.lineage import environment_info, git_info
from mlplatform.training.metrics import calibration_table, metrics_by_segment
from mlplatform.training.selection import (
    Candidate,
    CandidateResult,
    evaluate_candidates,
    select_candidate,
)
from mlplatform.training.thresholds import (
    calibrated_optimal_threshold,
    select_threshold_min_cost,
    threshold_metrics,
)


def test_threshold_metrics_counts() -> None:
    y = [1, 1, 0, 0, 0]
    score = [0.9, 0.2, 0.8, 0.1, 0.05]

    m = threshold_metrics(y, score, threshold=0.5, cost_fp=1, cost_fn=5)

    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 2)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["alert_rate"] == pytest.approx(0.4)
    assert m["cost_per_ticket"] == pytest.approx((1 * 1 + 5 * 1) / 5)


def test_min_cost_threshold_matches_theory_for_calibrated_scores() -> None:
    """Con probabilidades calibradas, el óptimo empírico ~ cost_fp / (cost_fp + cost_fn)."""
    rng = np.random.default_rng(0)
    score = rng.uniform(0, 1, 200_000)
    y = (rng.uniform(0, 1, score.size) < score).astype(int)  # calibrado por construcción

    threshold = select_threshold_min_cost(y, score, cost_fp=1, cost_fn=5)

    assert threshold == pytest.approx(calibrated_optimal_threshold(1, 5), abs=0.02)


def test_higher_miss_cost_lowers_the_threshold() -> None:
    rng = np.random.default_rng(1)
    score = rng.uniform(0, 1, 50_000)
    y = (rng.uniform(0, 1, score.size) < score).astype(int)

    cautious = select_threshold_min_cost(y, score, cost_fp=1, cost_fn=10)
    relaxed = select_threshold_min_cost(y, score, cost_fp=1, cost_fn=2)

    assert cautious < relaxed


def _result(name: str, pr_auc: float, complexity: int) -> CandidateResult:
    return CandidateResult(name, complexity, {"pr_auc": pr_auc}, 0.0, None)


def test_selection_prefers_simpler_model_within_tolerance() -> None:
    results = [_result("simple", 0.480, 1), _result("complex", 0.483, 2)]

    assert select_candidate(results, tolerance=0.005).name == "simple"
    assert select_candidate(results, tolerance=0.001).name == "complex"


def test_evaluate_candidates_does_not_mutate_the_template() -> None:
    X = pd.DataFrame({"x": np.arange(100.0)})
    y = (X["x"] > 50).astype(int)
    template = LogisticRegression()
    candidates = [Candidate("lr", template, 1), Candidate("prior", DummyClassifier(), 0)]

    results = evaluate_candidates(candidates, X, y, X, y)

    assert [r.name for r in results] == ["lr", "prior"]
    assert results[0].metrics["roc_auc"] > results[1].metrics["roc_auc"]
    assert not hasattr(template, "coef_")  # se entrenó un clon, no la plantilla


def test_calibration_table_detects_overconfident_scores() -> None:
    rng = np.random.default_rng(2)
    true_p = rng.uniform(0, 0.5, 20_000)
    y = (rng.uniform(0, 1, true_p.size) < true_p).astype(int)

    table = calibration_table(y, np.minimum(true_p * 2, 1), n_bins=5)

    assert (table["mean_predicted"] > table["observed_rate"] * 1.5).all()


def test_metrics_by_segment() -> None:
    table = metrics_by_segment(
        y_true=[1, 0, 1, 0],
        y_score=[0.9, 0.1, 0.2, 0.8],
        segments=pd.Series(["a", "a", "b", "b"], index=[10, 11, 12, 13]),
        threshold=0.5,
    )

    by_segment = table.set_index("segment")
    assert by_segment.loc["a", "recall"] == 1.0
    assert by_segment.loc["b", "recall"] == 0.0


def test_lineage_info() -> None:
    info = git_info()
    assert set(info) == {"commit", "dirty"}
    assert "scikit-learn" in environment_info()
