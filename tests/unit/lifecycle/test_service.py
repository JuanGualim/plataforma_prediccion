import pytest

from mlplatform.lifecycle.promotion import Evaluation
from mlplatform.lifecycle.service import LifecycleError, LifecycleService


def evaluator_with(scores: dict[str, float], baseline: float = 0.30):
    """Fake evaluator: each version has a fixed PR-AUC on the common window."""

    def metrics(pr_auc):
        return {"pr_auc": pr_auc, "brier": 0.10, "cost_per_ticket": 0.50}

    def evaluate(candidate, champion):
        return Evaluation(
            window_start="2025-06-01",
            n=500,
            candidate=metrics(scores[candidate.version]),
            champion=metrics(scores[champion.version]) if champion else None,
            baseline=metrics(baseline),
        )

    return evaluate


@pytest.fixture
def service(registry, event_log, make_contract):
    for version in ("1", "2", "3"):
        registry.add_version(version, make_contract())
    return LifecycleService(registry, event_log)


def test_promotion_moves_alias_tags_and_logs(service, registry, event_log) -> None:
    decision = service.promote("toy", "1", evaluator_with({"1": 0.4}), "ana", "primer modelo")

    assert decision.approved
    assert registry.aliases["champion"] == "1"
    assert registry.tags["1"]["status"] == "champion"
    event = event_log.events[-1]
    assert (event.event_type, event.from_version, event.to_version) == ("promoted", None, "1")
    assert event.actor == "ana"
    assert event.details["checks"]


def test_rejection_keeps_champion_and_is_logged(service, registry, event_log) -> None:
    scores = {"1": 0.40, "2": 0.35}
    service.promote("toy", "1", evaluator_with(scores), "ana", "v1")

    decision = service.promote("toy", "2", evaluator_with(scores), "ana", "v2")

    assert not decision.approved
    assert registry.aliases["champion"] == "1"
    assert registry.tags["2"]["status"] == "rejected"
    assert event_log.events[-1].event_type == "rejected"


def test_promoting_the_current_champion_is_an_error(service) -> None:
    service.promote("toy", "1", evaluator_with({"1": 0.4}), "ana", "v1")

    with pytest.raises(LifecycleError, match="already"):
        service.promote("toy", "1", evaluator_with({"1": 0.4}), "ana", "otra vez")


def test_rollback_restores_previous_champion(service, registry, event_log) -> None:
    scores = {"1": 0.40, "2": 0.45}
    service.promote("toy", "1", evaluator_with(scores), "ana", "v1")
    service.promote("toy", "2", evaluator_with(scores), "ana", "v2")
    assert registry.tags["1"]["status"] == "archived"

    event = service.rollback("toy", "beto", "latencia alta en v2")

    assert registry.aliases["champion"] == "1"
    assert registry.tags["2"]["status"] == "rolled_back"
    assert registry.tags["1"]["status"] == "champion"
    assert (event.from_version, event.to_version, event.actor) == ("2", "1", "beto")


def test_rollback_after_rollback_has_nowhere_to_go(service) -> None:
    scores = {"1": 0.40, "2": 0.45}
    service.promote("toy", "1", evaluator_with(scores), "ana", "v1")
    service.promote("toy", "2", evaluator_with(scores), "ana", "v2")
    service.rollback("toy", "beto", "incidente")

    with pytest.raises(LifecycleError, match="no previous champion"):
        service.rollback("toy", "beto", "otra vez")


def test_rollback_goes_to_the_champion_before_the_current_one(service, registry) -> None:
    scores = {"1": 0.40, "2": 0.45, "3": 0.50}
    for version in ("1", "2"):
        service.promote("toy", version, evaluator_with(scores), "ana", f"v{version}")
    service.rollback("toy", "beto", "problema con v2")  # champion = 1
    service.promote("toy", "3", evaluator_with(scores), "ana", "v3")  # 1 -> 3

    service.rollback("toy", "beto", "problema con v3")

    assert registry.aliases["champion"] == "1"


@pytest.mark.parametrize("reason", ["", "   "])
def test_rollback_requires_a_reason(service, reason) -> None:
    service.promote("toy", "1", evaluator_with({"1": 0.4}), "ana", "v1")
    with pytest.raises(LifecycleError, match="reason"):
        service.rollback("toy", "beto", reason)


def test_rollback_without_champion_is_an_error(service) -> None:
    with pytest.raises(LifecycleError, match="no champion"):
        service.rollback("toy", "beto", "incidente")
