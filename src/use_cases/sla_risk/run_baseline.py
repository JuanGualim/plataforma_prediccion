"""CLI: evalúa los baselines del modelo de SLA sobre los datos de PostgreSQL.

    uv run python -m use_cases.sla_risk.run_baseline [--test-days 30]

Baselines (cualquier modelo de la fase 2 debe superarlos):
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
from use_cases.sla_risk.dataset import TrainTestData, build_train_test, default_cutoff
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path("data/reports/sla_risk_baseline.json")


def evaluate_baselines(data: TrainTestData) -> dict[str, dict[str, float]]:
    results = {}

    prior = DummyClassifier(strategy="prior").fit(data.X_train, data.y_train)
    results["prior"] = binary_classification_metrics(
        data.y_test, prior.predict_proba(data.X_test)[:, 1]
    )

    rule = GroupRateClassifier(["priority", "customer_tier"]).fit(data.X_train, data.y_train)
    results["priority_x_tier"] = binary_classification_metrics(
        data.y_test, rule.predict_proba(data.X_test)[:, 1]
    )

    # Contrafactual con fuga: se salta select_features A PROPÓSITO, leyendo la fila completa.
    leak_cols = ["priority", "customer_tier", "reassignment_count"]
    leaky = GroupRateClassifier(leak_cols).fit(data.train_rows[leak_cols], data.y_train)
    results["LEAKY_with_reassignment_count"] = binary_classification_metrics(
        data.y_test, leaky.predict_proba(data.test_rows[leak_cols])[:, 1]
    )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    configure_logging()
    tickets = read_tickets(get_engine())
    data = build_train_test(tickets, default_cutoff(tickets, args.test_days))
    results = evaluate_baselines(data)

    table = pd.DataFrame(results).T[["n", "prevalence", "pr_auc", "roc_auc", "brier", "log_loss"]]
    logger.info("baseline results on test set:\n%s", table.round(4).to_string())

    report = {
        "use_case": "sla_risk",
        "cutoff": data.cutoff.isoformat(),
        "n_train": len(data.y_train),
        "n_test": len(data.y_test),
        "train_prevalence": float(data.y_train.mean()),
        "excluded_immature_train_rows": data.excluded_immature,
        "data_range": [
            tickets["created_at"].min().isoformat(),
            tickets["created_at"].max().isoformat(),
        ],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("report written to %s", args.output)


if __name__ == "__main__":
    main()
