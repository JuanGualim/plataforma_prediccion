"""CLI: evalúa los baselines del modelo de SLA sobre los datos de PostgreSQL.

    uv run python -m use_cases.sla_risk.run_baseline [--validation-days 30] [--test-days 30]

Baselines (cualquier modelo debe superarlos):
- prior: siempre predice la tasa histórica de incumplimiento (no distingue tickets).
- priority_x_tier: tasa histórica por prioridad y nivel de cliente (regla de experto).

Además reporta un CONTRAFACTUAL CON FUGA: el mismo baseline usando `reassignment_count`,
un dato que solo se conoce después de crear el ticket. Existe para mostrar cuánto infla
las métricas una fuga; nunca es un modelo válido.
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
from sklearn.dummy import DummyClassifier

from mlplatform.data.db import get_engine
from mlplatform.logging_config import configure_logging
from mlplatform.training.baselines import GroupRateClassifier
from mlplatform.training.metrics import binary_classification_metrics
from use_cases.sla_risk.dataset import DatasetSplits, build_splits, default_cutoffs
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path("data/reports/sla_risk_baseline.json")
LEAK_COLUMNS = ["priority", "customer_tier", "reassignment_count"]


def evaluate_baselines(splits: DatasetSplits) -> dict[str, dict[str, dict[str, float]]]:
    """Fit each baseline on train; report metrics on validation and test."""
    train = splits.train
    fitted = {
        "prior": (DummyClassifier(strategy="prior").fit(train.X, train.y), "X"),
        "priority_x_tier": (
            GroupRateClassifier(["priority", "customer_tier"]).fit(train.X, train.y),
            "X",
        ),
        # Contrafactual con fuga: se salta select_features A PROPÓSITO, leyendo la fila completa.
        "LEAKY_with_reassignment_count": (
            GroupRateClassifier(LEAK_COLUMNS).fit(train.rows[LEAK_COLUMNS], train.y),
            "rows",
        ),
    }
    results: dict[str, dict[str, dict[str, float]]] = {}
    for name, (model, source) in fitted.items():
        results[name] = {}
        for split_name in ("validation", "test"):
            split = getattr(splits, split_name)
            X = split.X if source == "X" else split.rows[LEAK_COLUMNS]
            results[name][split_name] = binary_classification_metrics(
                split.y, model.predict_proba(X)[:, 1]
            )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    configure_logging()
    tickets = read_tickets(get_engine())
    splits = build_splits(tickets, *default_cutoffs(tickets, args.validation_days, args.test_days))
    results = evaluate_baselines(splits)

    for split_name in ("validation", "test"):
        table = pd.DataFrame({name: r[split_name] for name, r in results.items()}).T
        logger.info("baselines on %s:\n%s", split_name, table.round(4).to_string())

    report = {
        "use_case": "sla_risk",
        "validation_cutoff": splits.validation_cutoff.isoformat(),
        "test_cutoff": splits.test_cutoff.isoformat(),
        "n": {s: len(getattr(splits, s).y) for s in ("train", "validation", "test")},
        "excluded_unknown_label": splits.excluded,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("report written to %s", args.output)


if __name__ == "__main__":
    main()
