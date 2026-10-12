import numpy as np
import pandas as pd
import pytest

from mlplatform.monitoring.drift import (
    ReferenceProfile,
    build_profile,
    compare,
    psi,
)
from mlplatform.monitoring.performance import compare_to_contract, live_metrics
from mlplatform.monitoring.rules import evaluate_rules
from mlplatform.monitoring.service import service_summary

RNG = np.random.default_rng(0)


def _frame(n: int, queue_mean: float = 100, channels=("email", "chat"), weights=(0.6, 0.4)):
    return pd.DataFrame(
        {
            "channel": RNG.choice(channels, size=n, p=weights),
            "queue": RNG.normal(queue_mean, 15, size=n),
        }
    )


@pytest.fixture(scope="module")
def profile() -> ReferenceProfile:
    reference = _frame(5000)
    return build_profile(
        reference,
        scores=RNG.beta(2, 10, size=5000),
        categorical=["channel"],
        numeric=["queue"],
        known_categories={"channel": ["email", "chat"]},
    )


def test_psi_is_zero_for_identical_and_grows_with_shift() -> None:
    assert psi([0.5, 0.5], [0.5, 0.5]) == pytest.approx(0)
    assert psi([0.5, 0.5], [0.6, 0.4]) < psi([0.5, 0.5], [0.9, 0.1])


def test_same_distribution_is_stable(profile) -> None:
    report = compare(profile, _frame(2000), RNG.beta(2, 10, size=2000))

    assert report.worst() == "ok"


def test_shifted_numeric_feature_raises_alert(profile) -> None:
    report = compare(profile, _frame(2000, queue_mean=140), RNG.beta(2, 10, size=2000))

    queue = next(f for f in report.features if f.name == "queue")
    assert queue.status == "alert"
    assert queue.current_mean > queue.reference_mean + 30


def test_new_category_is_an_alert_even_if_rare(profile) -> None:
    current = _frame(2000, channels=("email", "chat", "whatsapp"), weights=(0.59, 0.4, 0.01))

    report = compare(profile, current, RNG.beta(2, 10, size=2000))

    channel = next(f for f in report.features if f.name == "channel")
    assert channel.new_categories == ["whatsapp"]
    assert channel.status == "alert"


def test_score_drift_is_detected(profile) -> None:
    report = compare(profile, _frame(2000), RNG.beta(5, 10, size=2000))

    assert report.score.status == "alert"


def test_small_samples_are_not_judged(profile) -> None:
    report = compare(profile, _frame(50, queue_mean=200), RNG.beta(2, 10, size=50))

    assert {f.status for f in report.features} == {"insufficient_data"}


def test_profile_round_trips_through_json(profile) -> None:
    assert ReferenceProfile.model_validate_json(profile.model_dump_json()) == profile


def test_live_metrics_detect_miscalibration() -> None:
    y = (RNG.random(5000) < 0.30).astype(int)  # la tasa real subió a 30 %
    scores = np.clip(RNG.normal(0.15, 0.05, 5000), 0.01, 0.99)  # el modelo sigue diciendo ~15 %

    observed = live_metrics(y, scores, threshold=0.16, cost_fp=1, cost_fn=5)
    checks = compare_to_contract(observed, {"pr_auc": 0.30, "brier": 0.11, "cost_per_ticket": 0.5})

    gap = next(c for c in checks if c.name == "calibration_gap")
    assert observed["calibration_gap"] == pytest.approx(-0.15, abs=0.02)
    assert not gap.passed


def test_service_summary() -> None:
    requests = pd.DataFrame(
        {
            "status": [200] * 97 + [422, 500, 503],
            "latency_ms": np.linspace(10, 110, 100),
            "requested_at": pd.date_range("2025-01-01", periods=100, freq="s"),
        }
    )

    summary = service_summary(requests)

    assert summary["server_error_rate"] == pytest.approx(0.02)
    assert summary["client_error_rate"] == pytest.approx(0.01)
    assert 100 < summary["p95_ms"] < 110


def test_rules_assign_severity_and_runbook(profile) -> None:
    drift = compare(profile, _frame(2000, queue_mean=140), RNG.beta(2, 10, size=2000))
    observed = {"pr_auc": 0.2, "brier": 0.2, "calibration_gap": -0.12, "cost_per_ticket": 0.7}
    checks = compare_to_contract(observed, {"pr_auc": 0.45, "brier": 0.10, "cost_per_ticket": 0.45})
    service = {"requests": 100, "server_error_rate": 0.05, "p95_ms": 50}

    findings = evaluate_rules(service, drift, checks, n_labels=1000, label_coverage=0.9)

    by_check = {f.check: f for f in findings}
    assert by_check["server_error_rate"].severity == "SEV1"
    assert by_check["drift:queue"].severity == "SEV3"
    assert by_check["model:calibration_gap"].severity == "SEV2"
    assert by_check["model:calibration_gap"].runbook == "C"


def test_model_checks_wait_for_enough_labels(profile) -> None:
    checks = compare_to_contract(
        {"pr_auc": 0.1, "brier": 0.3, "calibration_gap": -0.2},
        {"pr_auc": 0.45, "brier": 0.10},
    )

    findings = evaluate_rules(None, None, checks, n_labels=120, label_coverage=0.1)

    assert findings == []
