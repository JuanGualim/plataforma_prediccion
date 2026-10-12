"""CLI: reporte de monitoreo del modelo de SLA en tres niveles (servicio, datos y modelo).

    uv run python -m use_cases.sla_risk.monitor --from 2025-08-01 --to 2025-10-01 [--version N]

- Ventanas por **tiempo del evento** (`created_at` del ticket), no por la hora en que se pidió
  la predicción: así una reproducción rápida de dos meses se analiza como dos meses.
- Solo tráfico `live` (el sintético se ignora).
- Datos y puntajes: comparados con el perfil de referencia guardado al entrenar la versión.
- Modelo: predicciones cruzadas con el resultado real disponible en `support.tickets`.
- Servicio: últimas `--service-hours` horas de `monitoring.requests`.

Escribe `data/reports/monitoring/<modelo>_v<versión>_<desde>_<hasta>.md` y `.json`.
"""

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa

from mlplatform.data.db import get_engine
from mlplatform.logging_config import configure_logging
from mlplatform.monitoring.drift import ReferenceProfile, compare
from mlplatform.monitoring.performance import MIN_LABELS, compare_to_contract, live_metrics
from mlplatform.monitoring.rules import evaluate_rules
from mlplatform.monitoring.service import service_summary
from mlplatform.registry.mlflow_registry import MlflowModelRegistry
from mlplatform.serialization import to_jsonable
from use_cases.sla_risk.contract import MODEL_NAME
from use_cases.sla_risk.monitoring import REFERENCE_PROFILE_ARTIFACT, monitoring_frame
from use_cases.sla_risk.simulator import BUSINESS_TZ

logger = logging.getLogger(__name__)
REPORTS_DIR = Path("data/reports/monitoring")
WEEKLY_FEATURES = ["open_tickets_in_queue", "channel", "priority"]

PREDICTIONS_SQL = sa.text("""
    SELECT DISTINCT ON (p.entity_id)
           p.entity_id, p.score, p.decision, p.threshold, p.features, p.predicted_at,
           t.sla_breached
    FROM monitoring.predictions p
    LEFT JOIN support.tickets t ON t.ticket_id::text = p.entity_id
    WHERE p.traffic_source = 'live' AND p.model_name = :model AND p.model_version = :version
      AND (p.features->>'created_at')::timestamptz >= :start
      AND (p.features->>'created_at')::timestamptz < :end
    ORDER BY p.entity_id, p.predicted_at DESC
""")
REQUESTS_SQL = sa.text("""
    SELECT status, latency_ms, requested_at FROM monitoring.requests
    WHERE traffic_source = 'live' AND requested_at >= now() - make_interval(hours => :hours)
""")


def load_predictions(engine, model: str, version: str, start, end) -> pd.DataFrame:
    with engine.connect() as conn:
        rows = pd.read_sql(
            PREDICTIONS_SQL,
            conn,
            params={"model": model, "version": version, "start": start, "end": end},
        )
    if rows.empty:
        return rows
    features = pd.json_normalize(rows["features"].tolist())
    frame = pd.concat([rows.drop(columns="features").reset_index(drop=True), features], axis=1)
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True).dt.tz_convert(BUSINESS_TZ)
    return frame.sort_values("created_at").reset_index(drop=True)


def weekly_table(frame: pd.DataFrame, profile: ReferenceProfile) -> pd.DataFrame:
    rows = []
    week_start = frame["created_at"].dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time
    for week, group in frame.groupby(week_start):
        drift = compare(profile, monitoring_frame(group), group["score"])
        psi = {f.name: f.psi for f in drift.features}
        labeled = group[group["sla_breached"].notna()]
        y = labeled["sla_breached"].astype(int)
        row = {
            "week": week.date().isoformat(),
            "n": len(group),
            "queue_mean": group["open_tickets_in_queue"].mean(),
            **{f"psi_{name}": psi[name] for name in WEEKLY_FEATURES},
            "psi_score": drift.score.psi,
            "mean_score": group["score"].mean(),
            "alert_rate": group["decision"].mean(),
            "label_coverage": len(labeled) / len(group),
            "observed_breach_rate": y.mean() if len(labeled) else np.nan,
            "calibration_gap": labeled["score"].mean() - y.mean() if len(labeled) else np.nan,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def run(model: str, version: str | None, start: str, end: str, service_hours: int) -> dict:
    registry = MlflowModelRegistry()
    version = version or registry.get_alias(model, "champion")
    contract = registry.get_contract(model, version)
    try:
        profile = ReferenceProfile.model_validate_json(
            registry.get_artifact_text(model, version, REFERENCE_PROFILE_ARTIFACT)
        )
    except Exception as error:
        raise SystemExit(
            f"version {version} has no reference profile (trained before phase 5?): {error}"
        ) from error

    engine = get_engine()
    start_ts = pd.Timestamp(start, tz=BUSINESS_TZ)
    end_ts = pd.Timestamp(end, tz=BUSINESS_TZ)
    frame = load_predictions(engine, model, version, start_ts, end_ts)
    with engine.connect() as conn:
        requests = pd.read_sql(REQUESTS_SQL, conn, params={"hours": service_hours})
    service = service_summary(requests)

    if frame.empty:
        raise SystemExit(f"no live predictions of {model} v{version} between {start} and {end}")

    drift = compare(profile, monitoring_frame(frame), frame["score"])
    labeled = frame[frame["sla_breached"].notna()]
    coverage = len(labeled) / len(frame)
    costs = contract.threshold.costs
    observed, checks = None, None
    if len(labeled) >= MIN_LABELS and labeled["sla_breached"].nunique() == 2:
        observed = live_metrics(
            labeled["sla_breached"].astype(int),
            labeled["score"],
            contract.threshold.value,
            costs["false_positive"],
            costs["false_negative"],
        )
        checks = compare_to_contract(observed, contract.test_metrics)
    findings = evaluate_rules(service, drift, checks, len(labeled), coverage)

    return {
        "model": model,
        "version": version,
        "window": [start, end],
        "reference": profile.description,
        "service": service,
        "data": {
            "n": drift.n,
            "worst_status": drift.worst(),
            "features": [asdict(f) for f in drift.features],
            "score": asdict(drift.score),
        },
        "model_quality": {
            "labels": len(labeled),
            "label_coverage": coverage,
            "observed": observed,
            "checks": [asdict(c) for c in checks] if checks else None,
        },
        "weekly": weekly_table(frame, profile).to_dict(orient="records"),
        "findings": [asdict(f) for f in findings],
    }


def to_markdown(r: dict) -> str:
    def table(rows: list[dict], columns: list[str], fmt: str = "{:.3f}") -> str:
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        for row in rows:
            cells = [
                fmt.format(row[c]) if isinstance(row[c], float) else str(row[c]) for c in columns
            ]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    findings = r["findings"]
    parts = [
        f"# Monitoreo {r['model']} v{r['version']} · {r['window'][0]} → {r['window'][1]}",
        f"Referencia: {r['reference']}. Solo tráfico `live`; ventanas por fecha de creación.",
        "## Hallazgos",
        table(findings, ["severity", "level", "check", "detail", "runbook"])
        if findings
        else "Ninguno.",
        "## Servicio",
        table([r["service"]], list(r["service"]), "{:.2f}"),
        f"## Datos y puntajes (n = {r['data']['n']}, peor estado: {r['data']['worst_status']})",
        table(
            [*r["data"]["features"], r["data"]["score"]],
            ["name", "psi", "status", "new_categories", "reference_mean", "current_mean"],
        ),
        f"## Modelo (etiquetas: {r['model_quality']['labels']}, "
        f"cobertura {r['model_quality']['label_coverage']:.0%})",
        table(r["model_quality"]["checks"], ["name", "expected", "observed", "limit", "passed"])
        if r["model_quality"]["checks"]
        else f"Sin etiquetas suficientes (mínimo {MIN_LABELS}).",
        "## Evolución semanal",
        table(r["weekly"], list(r["weekly"][0]), "{:.3f}") if r["weekly"] else "",
    ]
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--version", help="default: current champion")
    parser.add_argument("--service-hours", type=int, default=24)
    args = parser.parse_args(argv)

    configure_logging()
    report = to_jsonable(run(args.model, args.version, args.start, args.end, args.service_hours))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORTS_DIR / f"{args.model}_v{report['version']}_{args.start}_{args.end}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = to_markdown(report)
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    logger.info("monitoring report written to %s.md\n%s", stem, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
