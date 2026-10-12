"""CLI: genera el snapshot sintético, lo valida y lo carga en PostgreSQL.

uv run python -m use_cases.sla_risk.simulate [--days 180] [--seed 42] [--as-of DATE] [--dry-run]
"""

import argparse
import logging

import pandas as pd

from mlplatform.data.db import get_engine
from mlplatform.data.validation import ValidationReport
from mlplatform.logging_config import configure_logging
from use_cases.sla_risk.quality import validate_tickets
from use_cases.sla_risk.simulator import (
    BUSINESS_TZ,
    DriftScenario,
    SimulationConfig,
    SimulationResult,
    simulate,
)
from use_cases.sla_risk.storage import SCHEMA, replace_data

logger = logging.getLogger(__name__)


def validate_simulation(result: SimulationResult) -> ValidationReport:
    tickets, events = result.tickets, result.events
    report = validate_tickets(tickets)
    if events["event_at"].isna().any():
        report.issues.append("events with null event_at")
    if not events["ticket_id"].isin(tickets["ticket_id"]).all():
        report.issues.append("events reference unknown tickets")
    if (events["event_at"] > result.as_of).any():
        report.issues.append("events after the snapshot moment (as_of)")
    return report


def main(argv: list[str] | None = None) -> None:
    defaults = SimulationConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=defaults.days)
    parser.add_argument("--tickets-per-day", type=float, default=defaults.tickets_per_day)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument(
        "--as-of",
        help="snapshot moment (e.g. 2025-07-05); simulates that time has passed up to here",
    )
    parser.add_argument("--drift-start", help="date the world changes (e.g. 2025-08-15)")
    parser.add_argument(
        "--drift-capacity", type=float, help="queue capacity from --drift-start on (staff cut)"
    )
    parser.add_argument("--dry-run", action="store_true", help="simulate and validate only")
    args = parser.parse_args(argv)

    configure_logging()
    as_of = pd.Timestamp(args.as_of, tz=BUSINESS_TZ) if args.as_of else None
    drift = (
        DriftScenario(pd.Timestamp(args.drift_start).date(), queue_capacity=args.drift_capacity)
        if args.drift_start
        else None
    )
    config = SimulationConfig(
        days=args.days,
        tickets_per_day=args.tickets_per_day,
        seed=args.seed,
        as_of=as_of,
        drift=drift,
    )
    result = simulate(config)
    validate_simulation(result).raise_if_failed()

    labels = result.tickets["sla_breached"]
    logger.info(
        "simulated tickets=%d events=%d as_of=%s drift=%s breach_rate=%.3f unknown_labels=%d",
        len(result.tickets),
        len(result.events),
        result.as_of,
        drift,
        labels.dropna().astype(float).mean(),
        int(labels.isna().sum()),
    )
    if args.dry_run:
        logger.info("dry run: nothing written")
        return
    replace_data(get_engine(), result.tickets, result.events)
    logger.info("loaded into schema '%s' (tables tickets, ticket_events)", SCHEMA)


if __name__ == "__main__":
    main()
