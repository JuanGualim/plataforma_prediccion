"""CLI: genera el snapshot sintético, lo valida y lo carga en PostgreSQL.

uv run python -m use_cases.sla_risk.simulate [--days 180] [--seed 42] [--dry-run]
"""

import argparse
import logging

from mlplatform.data.db import get_engine
from mlplatform.data.validation import (
    ValidationReport,
    check_chronological,
    validate_against_catalog,
)
from mlplatform.logging_config import configure_logging
from use_cases.sla_risk.fields import TICKETS
from use_cases.sla_risk.simulator import SimulationConfig, SimulationResult, simulate
from use_cases.sla_risk.storage import SCHEMA, replace_data

logger = logging.getLogger(__name__)


def validate_simulation(result: SimulationResult) -> ValidationReport:
    tickets, events = result.tickets, result.events
    report = validate_against_catalog(tickets, TICKETS)
    report.extend(
        check_chronological(
            tickets, ["created_at", "first_response_at", "resolved_at", "closed_at"]
        )
    )
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
    parser.add_argument("--dry-run", action="store_true", help="simulate and validate only")
    args = parser.parse_args(argv)

    configure_logging()
    config = SimulationConfig(days=args.days, tickets_per_day=args.tickets_per_day, seed=args.seed)
    result = simulate(config)
    validate_simulation(result).raise_if_failed()

    labels = result.tickets["sla_breached"]
    logger.info(
        "simulated tickets=%d events=%d as_of=%s breach_rate=%.3f unknown_labels=%d",
        len(result.tickets),
        len(result.events),
        result.as_of,
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
