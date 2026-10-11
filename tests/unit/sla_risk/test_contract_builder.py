import pandas as pd
import pytest

from mlplatform.data.fingerprint import dataframe_fingerprint
from mlplatform.lifecycle.contract import REQUIRED_MODEL_CARD_SECTIONS, contract_violations
from mlplatform.serialization import to_jsonable
from use_cases.sla_risk.contract import build_contract
from use_cases.sla_risk.fields import FEATURES
from use_cases.sla_risk.model_card import detect_segment_limitations
from use_cases.sla_risk.train import TrainingConfig, train


@pytest.fixture(scope="module")
def contract(small_sim):
    config = TrainingConfig(validation_days=7, test_days=7, permutation_repeats=1)
    outcome = train(small_sim.tickets, config)
    return build_contract(outcome.report, small_sim.tickets)


def test_contract_is_complete(contract) -> None:
    assert [f.name for f in contract.signature.inputs] == FEATURES
    assert contract.threshold.costs == {"false_positive": 1.0, "false_negative": 5.0}
    assert contract.data_checks.passed
    assert len(contract.dataset.fingerprint) == 64
    for section in REQUIRED_MODEL_CARD_SECTIONS:
        assert section in contract.model_card


def test_only_code_state_can_violate_a_freshly_built_contract(contract) -> None:
    """En pruebas el árbol de git puede tener cambios; todo lo demás debe cumplirse."""
    other = [v for v in contract_violations(contract) if "uncommitted" not in v]

    assert other == []


def test_contract_round_trips_through_json(contract) -> None:
    restored = type(contract).model_validate_json(contract.model_dump_json())

    assert restored == contract


def test_limitations_are_detected_automatically() -> None:
    segments = {
        "priority": [
            {"segment": "critical", "n": 200, "recall": 0.26, "alert_rate": 0.18},
            {"segment": "low", "n": 900, "recall": 0.75, "alert_rate": 0.40},
            {"segment": "tiny", "n": 10, "recall": 0.0, "alert_rate": 1.0},  # muy pequeño
        ],
        "customer_tier": [{"segment": "enterprise", "n": 280, "recall": 0.98, "alert_rate": 0.93}],
    }

    findings = detect_segment_limitations(segments)

    assert len(findings) == 2
    assert "priority=critical" in findings[0]
    assert "customer_tier=enterprise" in findings[1]


def test_fingerprint_ignores_row_order_but_not_content() -> None:
    df = pd.DataFrame({"id": [1, 2, 3], "x": ["a", "b", "c"]})

    same = dataframe_fingerprint(df.iloc[::-1], ["id", "x"], ["id"])
    changed = dataframe_fingerprint(df.assign(x=["a", "b", "z"]), ["id", "x"], ["id"])

    assert dataframe_fingerprint(df, ["id", "x"], ["id"]) == same
    assert dataframe_fingerprint(df, ["id", "x"], ["id"]) != changed


def test_to_jsonable_removes_nan() -> None:
    assert to_jsonable({"a": float("nan"), "b": [1.0, float("inf")]}) == {
        "a": None,
        "b": [1.0, None],
    }
