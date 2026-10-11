import pandas as pd
import pytest

from use_cases.sla_risk.dataset import select_features
from use_cases.sla_risk.features import TIME_FEATURES, time_features
from use_cases.sla_risk.models import build_candidates


def test_time_features_use_local_business_time() -> None:
    # 2025-01-06 es lunes. 07:30 en Bogotá = 12:30 UTC.
    created = pd.Series(
        pd.to_datetime(["2025-01-06 12:30", "2025-01-06 15:00", "2025-01-11 15:00"], utc=True)
    )

    features = time_features(pd.DataFrame({"created_at": created}))

    assert list(features.columns) == TIME_FEATURES
    assert features["is_off_hours"].tolist() == [1, 0, 1]  # 07:30 · 10:00 · sábado
    assert features["is_weekend"].tolist() == [0, 0, 1]


def test_midnight_and_late_night_are_close() -> None:
    created = pd.Series(
        pd.to_datetime(["2025-01-06 23:50", "2025-01-07 00:10", "2025-01-07 12:00"])
    ).dt.tz_localize("America/Bogota")

    f = time_features(pd.DataFrame({"created_at": created}))

    def distance(a: int, b: int) -> float:
        return (
            (f.loc[a, ["hour_sin", "hour_cos"]] - f.loc[b, ["hour_sin", "hour_cos"]]) ** 2
        ).sum()

    assert distance(0, 1) < distance(0, 2)


@pytest.fixture(scope="module")
def fitted_logreg(small_sim):
    tickets = small_sim.tickets.dropna(subset=["sla_breached"])
    candidate = next(c for c in build_candidates() if c.name == "logreg")
    model = candidate.estimator.fit(select_features(tickets), tickets["sla_breached"].astype(int))
    return model, tickets


def test_pipeline_outputs_probabilities(fitted_logreg) -> None:
    model, tickets = fitted_logreg

    proba = model.predict_proba(select_features(tickets))[:, 1]

    assert ((proba >= 0) & (proba <= 1)).all()


def test_pipeline_survives_unseen_category(fitted_logreg) -> None:
    """Un canal nuevo en producción no debe tumbar el servicio de predicción."""
    model, tickets = fitted_logreg
    X = select_features(tickets.head(3))
    X["channel"] = "whatsapp"

    proba = model.predict_proba(X)[:, 1]

    assert len(proba) == 3


def test_raw_timestamp_never_reaches_the_model(fitted_logreg) -> None:
    model, _ = fitted_logreg

    names = list(model.named_steps["preprocess"].get_feature_names_out())

    assert "created_at" not in names
    assert set(TIME_FEATURES) <= set(names)
