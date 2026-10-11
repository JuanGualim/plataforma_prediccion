import pydantic
import pytest

from mlplatform.lifecycle.contract import contract_violations
from mlplatform.lifecycle.promotion import Evaluation, PromotionPolicy, evaluate_promotion


def test_valid_contract_has_no_violations(make_contract) -> None:
    assert contract_violations(make_contract()) == []


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"code": {"git_commit": None}}, "unknown git commit"),
        ({"code": {"git_dirty": True}}, "uncommitted"),
        ({"data_checks": {"passed": False, "issues": ["nulls"]}}, "data checks failed"),
        ({"model_card": "## Propósito\nsolo esto"}, "model card missing"),
        ({"primary_metric": "f1"}, "primary metric 'f1' missing"),
    ],
)
def test_policy_violations(make_contract, override, expected) -> None:
    assert any(expected in v for v in contract_violations(make_contract(**override)))


@pytest.mark.parametrize(
    "override",
    [
        {"threshold": {"value": 1.5}},  # umbral fuera de (0, 1)
        {"dataset": {"fingerprint": "corto"}},  # no es un sha256
        {"signature": {"inputs": [], "output": "p"}},  # firma vacía
    ],
)
def test_structurally_invalid_contracts_cannot_be_built(make_contract, override) -> None:
    with pytest.raises(pydantic.ValidationError):
        make_contract(**override)


def _evaluation(candidate=0.45, champion=0.40, baseline=0.30, window="2025-06-01", **extra):
    def metrics(pr_auc, brier=0.10, cost=0.50):
        return {"pr_auc": pr_auc, "brier": brier, "cost_per_ticket": cost}

    return Evaluation(
        window_start=window,
        n=500,
        candidate=extra.get("candidate_metrics", metrics(candidate)),
        champion=None if champion is None else metrics(champion),
        baseline=metrics(baseline),
    )


def _failed(decision) -> set[str]:
    return {c.name for c in decision.checks if not c.passed}


def test_first_promotion_only_needs_to_beat_baseline(make_contract) -> None:
    decision = evaluate_promotion(make_contract(), None, _evaluation(champion=None))

    assert decision.approved, decision.summary()


def test_candidate_worse_than_champion_is_rejected(make_contract) -> None:
    decision = evaluate_promotion(make_contract(), make_contract(), _evaluation(candidate=0.38))

    assert _failed(decision) == {"vs_champion"}


def test_candidate_not_beating_baseline_is_rejected(make_contract) -> None:
    decision = evaluate_promotion(make_contract(), None, _evaluation(candidate=0.29, champion=None))

    assert _failed(decision) == {"beats_baseline"}


def test_guardrail_blocks_better_ranking_with_worse_calibration(make_contract) -> None:
    worse_brier = {"pr_auc": 0.50, "brier": 0.20, "cost_per_ticket": 0.50}

    decision = evaluate_promotion(
        make_contract(), make_contract(), _evaluation(candidate_metrics=worse_brier)
    )

    assert _failed(decision) == {"guardrail_brier"}


def test_window_already_seen_by_champion_is_rejected(make_contract) -> None:
    champion = make_contract(dataset={"validation_end": "2025-06-15"})

    decision = evaluate_promotion(make_contract(), champion, _evaluation(window="2025-06-01"))

    assert "unseen_evaluation_window" in _failed(decision)


def test_invalid_contract_is_rejected_even_if_metrics_are_great(make_contract) -> None:
    dirty = make_contract(code={"git_dirty": True})

    decision = evaluate_promotion(dirty, None, _evaluation(candidate=0.9, champion=None))

    assert _failed(decision) == {"contract"}


def test_min_improvement_policy(make_contract) -> None:
    strict = PromotionPolicy(min_improvement=0.05)

    decision = evaluate_promotion(
        make_contract(), make_contract(), _evaluation(candidate=0.42, champion=0.40), strict
    )

    assert _failed(decision) == {"vs_champion"}
