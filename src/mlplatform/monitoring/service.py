"""Monitoreo del servicio: ¿la API responde, rápido y sin errores?

Se calcula a partir de `monitoring.requests` (una fila por llamada a /predict).
Los 4xx son errores del cliente (petición inválida); los 5xx, del servicio.
"""

import numpy as np
import pandas as pd


def service_summary(requests: pd.DataFrame) -> dict[str, float]:
    """`requests` needs columns: status, latency_ms, requested_at."""
    n = len(requests)
    if n == 0:
        return {"requests": 0}
    status = requests["status"].to_numpy()
    latency = requests["latency_ms"].to_numpy(dtype=float)
    span_s = (requests["requested_at"].max() - requests["requested_at"].min()).total_seconds()
    return {
        "requests": n,
        "server_error_rate": float(np.mean(status >= 500)),
        "client_error_rate": float(np.mean((status >= 400) & (status < 500))),
        "not_ready_rate": float(np.mean(status == 503)),
        "p50_ms": float(np.percentile(latency, 50)),
        "p95_ms": float(np.percentile(latency, 95)),
        "p99_ms": float(np.percentile(latency, 99)),
        "requests_per_minute": float(n / (span_s / 60)) if span_s > 0 else float(n),
    }
