"""CLI: ¿las variables de contexto operativo (T0*) mejoran el modelo de SLA? (fase 6)

    uv run python -m use_cases.sla_risk.feature_experiment

Requiere el mundo con drift de la fase 5 cargado hasta 2025-11-02:
    make data ARGS="--days 300 --drift-start 2025-08-15 --drift-capacity 85"

Para aislar el efecto de las variables, todo lo demás queda fijo: misma regresión logística
(el candidato que gana en producción), mismos cortes, misma regla de madurez de etiquetas y
mismo criterio de umbral (costo mínimo en validación). Tres escenarios:

- sin_drift: entrenar y probar antes del cambio de capacidad.
- drift_sin_reentrenar: entrenar antes del cambio y probar en septiembre (como la v4).
- drift_reentrenado: validación y prueba después del cambio (como la v5).

Las diferencias se acompañan de un intervalo bootstrap pareado (mismas filas remuestreadas
para la base y la variante): si el intervalo incluye el 0, la mejora no se distingue del ruido.

Escribe data/reports/features/feature_experiment.md y .json.
"""

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from mlplatform.data.db import get_engine
from mlplatform.logging_config import configure_logging
from mlplatform.monitoring.performance import live_metrics
from mlplatform.serialization import to_jsonable
from mlplatform.training.thresholds import select_threshold_min_cost
from use_cases.sla_risk.context_features import CONTEXT_FEATURES, context_features
from use_cases.sla_risk.dataset import label_known_at
from use_cases.sla_risk.features import NUMERIC, build_preprocessor
from use_cases.sla_risk.fields import TARGET
from use_cases.sla_risk.simulator import BUSINESS_TZ
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)
REPORTS_DIR = Path("data/reports/features")
COST_FP, COST_FN = 1.0, 5.0
VARIANTS = {
    "base": [],
    "+arrivals_24h": ["arrivals_24h"],
    "+breach_rate_7d": ["breach_rate_7d"],
    "+category_queue": ["category_queue"],
    "+todas": CONTEXT_FEATURES,
}


@dataclass(frozen=True)
class Scenario:
    name: str
    validation_cutoff: str
    test_cutoff: str
    test_start: str
    test_end: str
    description: str


SCENARIOS = [
    Scenario("sin_drift", "2025-05-01", "2025-06-01", "2025-06-01", "2025-07-15",
             "Entrenar y probar antes del cambio"),
    Scenario("drift_sin_reentrenar", "2025-06-02", "2025-07-02", "2025-09-01", "2025-10-01",
             "Entrenar antes del cambio, probar en septiembre (como la v4)"),
    Scenario("drift_reentrenado", "2025-09-17", "2025-10-01", "2025-10-01", "2025-10-15",
             "Validación y prueba después del cambio (como la v5)"),
]  # fmt: skip


def _ts(day: str) -> pd.Timestamp:
    return pd.Timestamp(day, tz=BUSINESS_TZ)


def split(rows: pd.DataFrame, s: Scenario) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train/validation/test with the same label-maturity rule as dataset.build_splits."""
    vc, tc = _ts(s.validation_cutoff), _ts(s.test_cutoff)
    created = rows["created_at"]
    train = rows[(created < vc) & label_known_at(rows, vc)]
    validation = rows[(created >= vc) & (created < tc) & label_known_at(rows, tc)]
    test = rows[(created >= _ts(s.test_start)) & (created < _ts(s.test_end))]
    return train, validation, test[test[TARGET].notna()]


def fit_and_score(train, validation, test, extra: list[str]) -> tuple[float, np.ndarray]:
    pipeline = Pipeline(
        [
            ("preprocess", build_preprocessor(True, numeric=NUMERIC + extra)),
            ("model", LogisticRegression(max_iter=2000)),
        ]
    )
    pipeline.fit(train, train[TARGET].astype(int))
    validation_scores = pipeline.predict_proba(validation)[:, 1]
    threshold = select_threshold_min_cost(
        validation[TARGET].astype(int), validation_scores, COST_FP, COST_FN
    )
    return threshold, pipeline.predict_proba(test)[:, 1]


def per_row_losses(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, np.ndarray]:
    """Brier and decision cost of each ticket (their means are the reported metrics)."""
    alert = scores >= threshold
    cost = COST_FP * (alert & (y == 0)) + COST_FN * (~alert & (y == 1))
    return {"brier": (scores - y) ** 2, "cost_per_ticket": cost}


def paired_bootstrap(
    base: dict[str, np.ndarray], variant: dict[str, np.ndarray], n_boot: int, seed: int
) -> dict[str, list[float]]:
    """95 % interval of mean(variant − base), resampling the same tickets for both."""
    rng = np.random.default_rng(seed)
    n = len(base["brier"])
    idx = rng.integers(0, n, size=(n_boot, n))
    return {
        key: np.percentile((variant[key] - base[key])[idx].mean(axis=1), [2.5, 97.5]).tolist()
        for key in base
    }


def run(tickets: pd.DataFrame, n_boot: int = 1000, seed: int = 42) -> dict:
    tickets = tickets.sort_values("created_at").reset_index(drop=True)
    rows = pd.concat([tickets, context_features(tickets, tickets)], axis=1)
    month = rows["created_at"].dt.tz_localize(None).dt.to_period("M").astype(str)
    monthly = rows.groupby(month)[["open_tickets_in_queue", *CONTEXT_FEATURES]].mean()

    results = []
    for scenario in SCENARIOS:
        train, validation, test = split(rows, scenario)
        y = test[TARGET].astype(int).to_numpy()
        scored = {name: fit_and_score(train, validation, test, extra)
                  for name, extra in VARIANTS.items()}  # fmt: skip
        losses = {name: per_row_losses(y, scores, th) for name, (th, scores) in scored.items()}
        for name, (threshold, scores) in scored.items():
            metrics = live_metrics(y, scores, threshold, COST_FP, COST_FN)
            interval = (
                None
                if name == "base"
                else paired_bootstrap(losses["base"], losses[name], n_boot, seed)
            )
            results.append(
                {
                    "scenario": scenario.name,
                    "variant": name,
                    "n_train": len(train),
                    "n_test": len(test),
                    "threshold": threshold,
                    **{k: metrics[k] for k in ("pr_auc", "brier", "calibration_gap")},
                    "cost_per_ticket": metrics["cost_per_ticket"],
                    "alert_rate": metrics["alert_rate"],
                    "delta_brier_ci95": interval and interval["brier"],
                    "delta_cost_ci95": interval and interval["cost_per_ticket"],
                }
            )
        logger.info("scenario %s done (train=%d test=%d)", scenario.name, len(train), len(test))
    return {
        "scenarios": [vars(s) for s in SCENARIOS],
        "costs": {"false_positive": COST_FP, "false_negative": COST_FN},
        "bootstrap": {"n": n_boot, "seed": seed},
        "monthly_means": monthly.reset_index(names="month").to_dict(orient="records"),
        "results": results,
    }


def to_markdown(report: dict) -> str:
    def interval(ci) -> str:
        if ci is None:
            return "—"
        mark = " ✱" if ci[1] < 0 or ci[0] > 0 else ""
        return f"[{ci[0]:+.4f}, {ci[1]:+.4f}]{mark}"

    lines = [
        "# Experimento de variables de contexto (fase 6)",
        "",
        "✱ = el intervalo no incluye 0 (diferencia distinguible del ruido). Negativo = mejora.",
        "",
        "## Promedios mensuales",
        "",
        "| Mes | Cola | Llegadas 24 h | Tasa incumpl. 7 d | Cola de la categoría |",
        "|---|---|---|---|---|",
    ]
    for m in report["monthly_means"]:
        lines.append(
            f"| {m['month']} | {m['open_tickets_in_queue']:.1f} | {m['arrivals_24h']:.1f} | "
            f"{m['breach_rate_7d']:.3f} | {m['category_queue']:.1f} |"
        )
    for s in report["scenarios"]:
        rows = [r for r in report["results"] if r["scenario"] == s["name"]]
        lines += [
            "",
            f"## {s['name']}: {s['description']}",
            f"Prueba {s['test_start']} → {s['test_end']} (n = {rows[0]['n_test']}); "
            f"entrenamiento n = {rows[0]['n_train']}.",
            "",
            "| Variante | Umbral | PR-AUC | Brier | Brecha | Costo | Alertas "
            "| Δ Brier IC95 | Δ costo IC95 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            cells = [
                r["variant"],
                f"{r['threshold']:.2f}",
                f"{r['pr_auc']:.3f}",
                f"{r['brier']:.4f}",
                f"{r['calibration_gap']:+.3f}",
                f"{r['cost_per_ticket']:.3f}",
                f"{r['alert_rate']:.2f}",
                interval(r["delta_brier_ci95"]),
                interval(r["delta_cost_ci95"]),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)

    configure_logging()
    report = to_jsonable(run(read_tickets(get_engine()), n_boot=args.bootstrap))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "feature_experiment.json").write_text(json.dumps(report, indent=2))
    markdown = to_markdown(report)
    (REPORTS_DIR / "feature_experiment.md").write_text(markdown, encoding="utf-8")
    logger.info("report written to %s\n%s", REPORTS_DIR / "feature_experiment.md", markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
