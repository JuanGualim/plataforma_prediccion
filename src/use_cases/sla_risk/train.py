"""CLI: entrena, selecciona y evalúa el modelo de riesgo de SLA.

    uv run python -m use_cases.sla_risk.train [--cost-fp 1] [--cost-fn 5] [--candidates a,b]

Flujo (cada decisión se toma con el conjunto que corresponde):

1. Particiones temporales train / validation / test (dataset.build_splits).
2. Candidatos entrenados en train y comparados en validation (PR-AUC).
3. Selección: el más simple dentro de una tolerancia del mejor.
4. Umbral: el que minimiza el costo esperado en validation.
5. Test se usa UNA vez, con modelo y umbral ya fijos, junto al baseline de referencia.
6. Se registra en MLflow como versión candidata, con su contrato de despliegue
   (use_cases.sla_risk.registration). Pasar a champion requiere la puerta de promoción.
"""

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sklearn.inspection import permutation_importance

from mlplatform.data.db import get_engine
from mlplatform.logging_config import configure_logging
from mlplatform.serialization import to_jsonable
from mlplatform.training.baselines import GroupRateClassifier
from mlplatform.training.lineage import environment_info, git_info
from mlplatform.training.metrics import (
    binary_classification_metrics,
    calibration_table,
    metrics_by_segment,
)
from mlplatform.training.selection import evaluate_candidates, select_candidate
from mlplatform.training.thresholds import (
    calibrated_optimal_threshold,
    select_threshold_min_cost,
    threshold_metrics,
)
from use_cases.sla_risk.dataset import build_splits, default_cutoffs
from use_cases.sla_risk.fields import FEATURES, TARGET
from use_cases.sla_risk.models import build_candidates
from use_cases.sla_risk.monitoring import reference_profile
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)
SEGMENT_COLUMNS = ["customer_tier", "priority", "channel"]


@dataclass(frozen=True)
class TrainingConfig:
    validation_days: int = 30
    test_days: int = 30
    selection_metric: str = "pr_auc"
    selection_tolerance: float = 0.005
    # Supuesto de negocio (documentado): no detectar un incumplimiento cuesta 5 veces más
    # que escalar un ticket que no lo necesitaba.
    cost_false_positive: float = 1.0
    cost_false_negative: float = 5.0
    random_state: int = 42
    permutation_repeats: int = 5
    # Restringe los candidatos por nombre (None = todos). Útil para experimentos dirigidos.
    candidate_names: tuple[str, ...] | None = None


@dataclass(frozen=True)
class TrainingOutcome:
    model: Any
    threshold: float
    report: dict


def train(tickets: pd.DataFrame, config: TrainingConfig | None = None) -> TrainingOutcome:
    config = config or TrainingConfig()
    cost_fp, cost_fn = config.cost_false_positive, config.cost_false_negative
    splits = build_splits(
        tickets, *default_cutoffs(tickets, config.validation_days, config.test_days)
    )
    train_set, val, test = splits.train, splits.validation, splits.test

    # 2-3. Candidatos y selección (solo validation).
    candidates = build_candidates(config.random_state)
    if config.candidate_names:
        candidates = [c for c in candidates if c.name in config.candidate_names]
        if not candidates:
            raise ValueError(f"no candidate matches {config.candidate_names}")
    results = evaluate_candidates(candidates, train_set.X, train_set.y, val.X, val.y)
    selected = select_candidate(results, config.selection_metric, config.selection_tolerance)
    model = selected.model

    # 4. Umbral (solo validation).
    val_scores = model.predict_proba(val.X)[:, 1]
    threshold = select_threshold_min_cost(val.y, val_scores, cost_fp, cost_fn)

    # Referencia: el mejor baseline de la fase 1, con su propio umbral elegido igual.
    baseline = GroupRateClassifier(["priority", "customer_tier"]).fit(train_set.X, train_set.y)
    baseline_val_scores = baseline.predict_proba(val.X)[:, 1]
    baseline_threshold = select_threshold_min_cost(val.y, baseline_val_scores, cost_fp, cost_fn)

    # 5. Test: una sola vez, todo ya decidido.
    test_scores = model.predict_proba(test.X)[:, 1]
    baseline_test_scores = baseline.predict_proba(test.X)[:, 1]
    positives = float(test.y.mean())
    test_report = {
        "model": {
            "ranking": binary_classification_metrics(test.y, test_scores),
            "decision": threshold_metrics(test.y, test_scores, threshold, cost_fp, cost_fn),
        },
        "baseline_priority_x_tier": {
            "ranking": binary_classification_metrics(test.y, baseline_test_scores),
            "decision": threshold_metrics(
                test.y, baseline_test_scores, baseline_threshold, cost_fp, cost_fn
            ),
        },
        "policy_cost_per_ticket": {
            "never_alert": cost_fn * positives,
            "always_alert": cost_fp * (1 - positives),
        },
        "calibration": calibration_table(test.y, test_scores).to_dict(orient="records"),
        "segments": {
            col: metrics_by_segment(test.y, test_scores, test.rows[col], threshold).to_dict(
                orient="records"
            )
            for col in SEGMENT_COLUMNS
        },
    }
    alerts = test_report["model"]["decision"]["tp"] + test_report["model"]["decision"]["fp"]
    test_report["model"]["decision"]["alerts_per_day"] = alerts / config.test_days

    model_pr_auc = test_report["model"]["ranking"]["pr_auc"]
    baseline_pr_auc = test_report["baseline_priority_x_tier"]["ranking"]["pr_auc"]
    beats_baseline = model_pr_auc > baseline_pr_auc
    if not beats_baseline:
        logger.warning(
            "model does NOT beat the baseline on test: %.4f <= %.4f", model_pr_auc, baseline_pr_auc
        )

    importance = permutation_importance(
        model,
        val.X,
        val.y,
        scoring="average_precision",
        n_repeats=config.permutation_repeats,
        random_state=config.random_state,
    )

    report = {
        "use_case": "sla_risk",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": asdict(config),
        "data": {
            "range": [str(tickets["created_at"].min()), str(tickets["created_at"].max())],
            "validation_cutoff": str(splits.validation_cutoff),
            "test_cutoff": str(splits.test_cutoff),
            "n": {name: len(getattr(splits, name).y) for name in ("train", "validation", "test")},
            "prevalence": {
                name: float(getattr(splits, name).y.mean())
                for name in ("train", "validation", "test")
            },
            "excluded_unknown_label": splits.excluded,
        },
        "features": {"input_columns": FEATURES, "target": TARGET},
        "candidates_validation": [
            {"name": r.name, "complexity": r.complexity, "fit_seconds": r.fit_seconds, **r.metrics}
            for r in results
        ],
        "selected": {"name": selected.name, "validation": selected.metrics},
        "threshold": {
            "value": threshold,
            "calibrated_theoretical_optimum": calibrated_optimal_threshold(cost_fp, cost_fn),
            "validation_decision": threshold_metrics(
                val.y, val_scores, threshold, cost_fp, cost_fn
            ),
            "baseline_threshold": baseline_threshold,
        },
        "test": test_report,
        "beats_baseline_on_test": beats_baseline,
        "permutation_importance_validation": dict(
            sorted(
                zip(FEATURES, importance.importances_mean.tolist(), strict=True),
                key=lambda item: -item[1],
            )
        ),
        "lineage": {"git": git_info(), "environment": environment_info()},
        # Perfil de referencia para el monitoreo: distribuciones en la ventana de prueba (que
        # el modelo no usó para aprender ni para elegir umbral) y categorías vistas al entrenar.
        "reference_profile": reference_profile(
            test.rows,
            test_scores,
            train_set.rows,
            description=f"test window from {splits.test_cutoff.date()}",
        ).model_dump(),
    }
    return TrainingOutcome(model=model, threshold=threshold, report=to_jsonable(report))


def _log_summary(report: dict) -> None:
    candidates = pd.DataFrame(report["candidates_validation"]).set_index("name")
    logger.info(
        "candidates on validation:\n%s",
        candidates[["pr_auc", "roc_auc", "brier", "log_loss", "fit_seconds"]].round(4).to_string(),
    )
    t = report["threshold"]
    logger.info(
        "selected=%s threshold=%.2f (calibrated theory %.3f)",
        report["selected"]["name"],
        t["value"],
        t["calibrated_theoretical_optimum"],
    )
    test = report["test"]
    rows = {
        "model": {**test["model"]["ranking"], **test["model"]["decision"]},
        "baseline": {
            **test["baseline_priority_x_tier"]["ranking"],
            **test["baseline_priority_x_tier"]["decision"],
        },
    }
    cols = ["pr_auc", "roc_auc", "brier", "threshold", "precision", "recall", "alert_rate"]
    cols.append("cost_per_ticket")
    logger.info("test (evaluated once):\n%s", pd.DataFrame(rows).T[cols].round(4).to_string())
    logger.info("policy cost per ticket: %s", test["policy_cost_per_ticket"])
    importance = report["permutation_importance_validation"]
    logger.info(
        "permutation importance (validation, PR-AUC drop): %s",
        {name: round(value, 4) for name, value in importance.items()},
    )


def main(argv: list[str] | None = None) -> None:
    # Import diferido: registrar requiere MLflow; entrenar (train()) no.
    from use_cases.sla_risk.registration import register_candidate

    defaults = TrainingConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--validation-days", type=int, default=defaults.validation_days)
    parser.add_argument("--test-days", type=int, default=defaults.test_days)
    parser.add_argument("--cost-fp", type=float, default=defaults.cost_false_positive)
    parser.add_argument("--cost-fn", type=float, default=defaults.cost_false_negative)
    parser.add_argument("--candidates", help="comma-separated candidate names (default: all)")
    args = parser.parse_args(argv)

    configure_logging()
    config = TrainingConfig(
        validation_days=args.validation_days,
        test_days=args.test_days,
        cost_false_positive=args.cost_fp,
        cost_false_negative=args.cost_fn,
        candidate_names=tuple(args.candidates.split(",")) if args.candidates else None,
    )
    tickets = read_tickets(get_engine())
    outcome = train(tickets, config)
    _log_summary(outcome.report)
    registered = register_candidate(outcome, tickets)
    logger.info(
        "registered %s version %s (run %s) as candidate; contract violations: %s",
        registered.model_name,
        registered.version,
        registered.run_id,
        registered.violations or "none",
    )
    logger.info("next step: make promote VERSION=%s", registered.version)


if __name__ == "__main__":
    main()
