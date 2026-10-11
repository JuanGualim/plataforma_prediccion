"""CLI del ciclo de vida del modelo de SLA: estado, promoción y rollback.

uv run python -m use_cases.sla_risk.registry_cli status
uv run python -m use_cases.sla_risk.registry_cli promote [--version N] [--reason "..."]
uv run python -m use_cases.sla_risk.registry_cli rollback --reason "..."
"""

import argparse
import getpass
import logging
import sys

import pandas as pd

from mlplatform.data.db import get_engine
from mlplatform.lifecycle.promotion import PromotionPolicy
from mlplatform.lifecycle.service import CHAMPION, LifecycleError, LifecycleService
from mlplatform.logging_config import configure_logging
from mlplatform.registry.event_log import PostgresEventLog
from mlplatform.registry.mlflow_registry import MlflowModelRegistry
from use_cases.sla_risk.contract import MODEL_NAME
from use_cases.sla_risk.evaluation import SlaRiskEvaluator
from use_cases.sla_risk.storage import read_tickets

logger = logging.getLogger(__name__)


def build_service(
    policy: PromotionPolicy | None = None,
    event_schema: str = "governance",
    tracking_uri: str | None = None,
) -> tuple[LifecycleService, MlflowModelRegistry]:
    registry = MlflowModelRegistry(tracking_uri)
    events = PostgresEventLog(get_engine(), schema=event_schema)
    return LifecycleService(registry, events, policy), registry


def _v(version: str | None) -> str:
    return f"v{version}" if version else "(none)"


def show_status(service: LifecycleService, registry: MlflowModelRegistry, model: str) -> None:
    versions = pd.DataFrame(registry.describe_versions(model))
    if not versions.empty:
        versions["created"] = pd.to_datetime(versions["created"], unit="ms").dt.strftime(
            "%Y-%m-%d %H:%M"
        )
    logger.info("model %s, champion = v%s\n%s", model, registry.get_alias(model, CHAMPION),
                versions.to_string(index=False))  # fmt: skip
    history = service.events.history(model)[-10:]
    lines = [
        f"{e.created_at[:19]}  {e.event_type:<11} {_v(e.from_version)} -> {_v(e.to_version)}  "
        f"by {e.actor}: {e.reason}"
        for e in history
    ]
    logger.info("last events:\n%s", "\n".join(lines) or "(none)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--actor", default=getpass.getuser())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    promote = sub.add_parser("promote")
    promote.add_argument("--version", help="default: latest registered version")
    promote.add_argument("--reason", default="new candidate after training")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    configure_logging()
    service, registry = build_service()
    try:
        if args.command == "status":
            show_status(service, registry, args.model)
        elif args.command == "promote":
            version = args.version or registry.latest_version(args.model)
            evaluator = SlaRiskEvaluator(read_tickets(get_engine()))
            decision = service.promote(args.model, version, evaluator, args.actor, args.reason)
            logger.info("promotion of %s v%s:\n%s", args.model, version, decision.summary())
            return 0 if decision.approved else 2
        elif args.command == "rollback":
            event = service.rollback(args.model, args.actor, args.reason)
            logger.info("rollback: champion v%s -> v%s", event.from_version, event.to_version)
    except LifecycleError as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
