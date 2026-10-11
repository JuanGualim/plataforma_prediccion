import numpy as np
import pandas as pd
import pytest

from mlplatform.training.baselines import GroupRateClassifier
from mlplatform.training.metrics import binary_classification_metrics
from mlplatform.training.splits import temporal_split


def test_temporal_split_has_no_overlap() -> None:
    df = pd.DataFrame({"t": pd.date_range("2025-01-01", periods=10, freq="D")})

    train, test = temporal_split(df, "t", pd.Timestamp("2025-01-08"))

    assert train["t"].max() < pd.Timestamp("2025-01-08") <= test["t"].min()
    assert len(train) + len(test) == len(df)


def test_temporal_split_rejects_empty_side() -> None:
    df = pd.DataFrame({"t": pd.date_range("2025-01-01", periods=3, freq="D")})
    with pytest.raises(ValueError, match="empty"):
        temporal_split(df, "t", pd.Timestamp("2030-01-01"))


def test_constant_score_metrics_equal_no_information() -> None:
    y = np.array([0] * 90 + [1] * 10)

    metrics = binary_classification_metrics(y, np.full(len(y), 0.1))

    assert metrics["prevalence"] == pytest.approx(0.1)
    assert metrics["pr_auc"] == pytest.approx(0.1)  # sin información, PR-AUC = prevalencia
    assert metrics["roc_auc"] == pytest.approx(0.5)


def test_group_rate_smoothing_and_unseen_groups() -> None:
    X = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4})
    y = [1, 1, 1, 1, 0, 0, 0, 0]  # tasa global 0.5

    model = GroupRateClassifier(["g"], smoothing=4).fit(X, y)
    proba = model.predict_proba(pd.DataFrame({"g": ["a", "b", "never_seen"]}))[:, 1]

    # (4 + 4*0.5) / (4 + 4) = 0.75: la tasa observada (1.0) se "encoge" hacia la global
    assert proba == pytest.approx([0.75, 0.25, 0.5])
