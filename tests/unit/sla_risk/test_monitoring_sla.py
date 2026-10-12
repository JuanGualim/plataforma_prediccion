import pandas as pd

from mlplatform.monitoring.drift import compare
from use_cases.sla_risk.fields import FEATURES
from use_cases.sla_risk.monitor import to_markdown, weekly_table
from use_cases.sla_risk.monitoring import MONITORED_NUMERIC, monitoring_frame, reference_profile
from use_cases.sla_risk.replay import instances_from


def test_replay_only_sends_what_is_known_at_creation(small_sim) -> None:
    instances = instances_from(small_sim.tickets.head(3))

    assert set(instances[0]) == {"ticket_id", *FEATURES}
    assert isinstance(instances[0]["created_at"], str)


def test_reference_profile_matches_its_own_data(small_sim) -> None:
    rows = small_sim.tickets
    scores = pd.Series(0.15, index=rows.index) + rows["open_tickets_in_queue"] / 10_000

    profile = reference_profile(rows, scores, rows, description="test")
    report = compare(profile, monitoring_frame(rows), scores)

    assert set(profile.numeric) == set(MONITORED_NUMERIC)
    assert report.worst() == "ok"


def test_weekly_table_and_markdown(small_sim) -> None:
    rows = small_sim.tickets.dropna(subset=["sla_breached"]).copy()
    rows["score"] = 0.15
    rows["decision"] = False
    profile = reference_profile(rows, rows["score"], rows, description="test")

    weekly = weekly_table(rows, profile)

    assert weekly["n"].sum() == len(rows)
    assert weekly["label_coverage"].eq(1.0).all()
    report = {
        "model": "sla_risk",
        "version": "9",
        "window": ["a", "b"],
        "reference": "test",
        "service": {"requests": 0},
        "data": {
            "n": 1,
            "worst_status": "ok",
            "features": [],
            "score": {
                "name": "score",
                "psi": 0.0,
                "status": "ok",
                "new_categories": [],
                "reference_mean": 0.1,
                "current_mean": 0.1,
            },
        },
        "model_quality": {"labels": 0, "label_coverage": 0.0, "checks": None},
        "weekly": weekly.to_dict(orient="records"),
        "findings": [],
    }
    assert "## Evolución semanal" in to_markdown(report)
