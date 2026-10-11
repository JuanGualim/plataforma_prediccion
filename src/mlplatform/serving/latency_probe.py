"""Sonda de latencia: envía N peticiones secuenciales a /predict y reporta percentiles.

    uv run python -m mlplatform.serving.latency_probe --url http://localhost:8000 \\
        --payload infra/serving/example_request.json --requests 300

Mide desde el cliente (incluye red local y serialización JSON). Es una medición de
referencia en una máquina de desarrollo, no un benchmark de capacidad: las peticiones van
de una en una, sin concurrencia.
"""

import argparse
import json
import logging
import time
import urllib.request
from pathlib import Path

import numpy as np

from mlplatform.logging_config import configure_logging

logger = logging.getLogger(__name__)


def probe(url: str, payload: dict, n_requests: int, warmup: int = 10) -> dict[str, float]:
    body = json.dumps(payload).encode("utf-8")

    def call() -> float:
        request = urllib.request.Request(
            f"{url}/predict",
            data=body,
            headers={"content-type": "application/json", "x-traffic-source": "synthetic"},
        )
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        return (time.perf_counter() - start) * 1000

    for _ in range(warmup):  # la primera petición paga costos únicos (conexiones, cachés)
        call()
    started = time.perf_counter()
    latencies = np.array([call() for _ in range(n_requests)])
    elapsed = time.perf_counter() - started
    return {
        "requests": n_requests,
        "instances_per_request": len(payload["instances"]),
        "p50_ms": float(np.percentile(latencies, 50)),
        "p95_ms": float(np.percentile(latencies, 95)),
        "p99_ms": float(np.percentile(latencies, 99)),
        "max_ms": float(latencies.max()),
        "requests_per_second": n_requests / elapsed,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--batch", type=int, help="repeat the first instance to this batch size")
    args = parser.parse_args(argv)

    configure_logging()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    if args.batch:
        payload = {"instances": [payload["instances"][0]] * args.batch}
    result = probe(args.url, payload, args.requests)
    logger.info("latency: %s", {k: round(v, 2) for k, v in result.items()})


if __name__ == "__main__":
    main()
