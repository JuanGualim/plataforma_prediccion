"""CLI: simula el sistema de tickets de producción llamando a la API de predicción.

    uv run python -m use_cases.sla_risk.replay --from 2025-08-01 --to 2025-10-01 \\
        --days 300 --drift-start 2025-08-15 --drift-capacity 85

Toma del simulador los tickets creados en la ventana y los envía a /predict en orden de
creación, **solo con los campos conocidos en T0**, como lo haría el sistema real al crear cada
ticket. Es tráfico `live`: representa la producción que el monitoreo debe vigilar.

Los argumentos del mundo (--days, --seed, --drift-*) deben ser los mismos de `make data`: el
resultado real de cada ticket llegará después, cuando el snapshot de la base de datos avance.
Por velocidad se envían lotes de tickets consecutivos; en producción llegarían de a uno.
"""

import argparse
import json
import logging
import urllib.request

import pandas as pd

from mlplatform.logging_config import configure_logging
from mlplatform.serialization import to_jsonable
from use_cases.sla_risk.fields import FEATURES
from use_cases.sla_risk.simulator import BUSINESS_TZ, DriftScenario, SimulationConfig, simulate

logger = logging.getLogger(__name__)


def instances_from(tickets: pd.DataFrame) -> list[dict]:
    """T0 payload of each ticket: identifier plus model inputs, nothing else."""
    rows = tickets[["ticket_id", *FEATURES]].copy()
    rows["created_at"] = rows["created_at"].map(lambda t: t.isoformat())
    return rows.to_dict(orient="records")


def send(url: str, instances: list[dict]) -> dict:
    request = urllib.request.Request(
        f"{url}/predict",
        data=json.dumps({"instances": to_jsonable(instances)}).encode("utf-8"),
        headers={"content-type": "application/json", "x-traffic-source": "live"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main(argv: list[str] | None = None) -> None:
    defaults = SimulationConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--days", type=int, default=defaults.days)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--drift-start")
    parser.add_argument("--drift-capacity", type=float)
    parser.add_argument("--batch", type=int, default=50)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args(argv)

    configure_logging()
    drift = (
        DriftScenario(pd.Timestamp(args.drift_start).date(), queue_capacity=args.drift_capacity)
        if args.drift_start
        else None
    )
    tickets = simulate(SimulationConfig(days=args.days, seed=args.seed, drift=drift)).tickets
    start = pd.Timestamp(args.start, tz=BUSINESS_TZ)
    end = pd.Timestamp(args.end, tz=BUSINESS_TZ)
    window = tickets[(tickets["created_at"] >= start) & (tickets["created_at"] < end)]
    instances = instances_from(window)

    versions: dict[str, int] = {}
    for i in range(0, len(instances), args.batch):
        response = send(args.url, instances[i : i + args.batch])
        version = response["model_version"]
        versions[version] = versions.get(version, 0) + len(response["predictions"])
        if (i // args.batch) % 40 == 0:
            logger.info("sent %d/%d tickets", min(i + args.batch, len(instances)), len(instances))
    logger.info(
        "replayed %d tickets from %s to %s; served by versions %s",
        len(instances),
        start.date(),
        end.date(),
        versions,
    )


if __name__ == "__main__":
    main()
