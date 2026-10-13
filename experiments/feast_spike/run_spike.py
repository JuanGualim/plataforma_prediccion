"""Spike de Feast (fase 6): ¿Feast da los mismos valores que nuestra implementación, y a qué costo?

    make feast-spike        (requiere `make feast-export` antes)

Pasos y lo que mide cada uno:
1. apply: registra entidades y vistas.
2. Historia: point-in-time join de Feast para los 31 mil tickets. **Paridad**: debe coincidir
   exactamente con nuestro cálculo en la hora en punto anterior a T0 (tabla
   feast_spike.expected). Además se mide cuánto difiere del valor exacto en T0: es el costo de
   materializar cada hora en vez de calcular al instante.
3. materialize: copia el último valor de cada clave al almacenamiento en línea.
4. En línea: latencia de leer las variables de un ticket con Feast.
5. Alternativas sin feature store, con paridad y latencia:
   a) SQL que calcula las variables al momento sobre support.tickets (sin índices);
   b) nuestra propia tabla horaria, leyendo la última fila por clave primaria.

Escribe data/reports/features/feast_spike.json en el proyecto principal.
"""

import json
import os
import statistics
import subprocess
import sys
import time
from datetime import timedelta
from importlib import metadata
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(__file__).resolve().parent / "feature_repo"
REPORTS = ROOT / "data" / "reports" / "features"
load_dotenv(ROOT / ".env")
os.environ["FEAST_USAGE"] = "False"  # sin telemetría (mismo criterio que con MLflow)

import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
from feast import FeatureStore  # noqa: E402

sys.path.insert(0, str(REPO))
from definitions import category, category_context, operations, team  # noqa: E402

FEATURES = [
    "operations:arrivals_24h",
    "operations:breach_rate_7d",
    "category_context:category_queue",
]
NAMES = ["arrivals_24h", "breach_rate_7d", "category_queue"]
ONLINE_CALLS = 300

ON_DEMAND_SQL = """
WITH t AS (
    SELECT created_at, category, resolved_at, sla_breached,
           CASE WHEN sla_breached THEN created_at + make_interval(hours => sla_hours)
                ELSE resolved_at END AS known_at
    FROM support.tickets
), recent AS (
    SELECT sla_breached FROM t
    WHERE sla_breached IS NOT NULL
      AND known_at >= %(t)s - interval '7 days' AND known_at < %(t)s
)
SELECT
    (SELECT count(*) FROM t
      WHERE created_at >= %(t)s - interval '24 hours' AND created_at < %(t)s) AS arrivals_24h,
    (SELECT CASE WHEN count(*) >= 50 THEN avg(sla_breached::int) ELSE 0.15 END
       FROM recent) AS breach_rate_7d,
    (SELECT count(*) FROM t
      WHERE category = %(c)s AND created_at < %(t)s
        AND (resolved_at IS NULL OR resolved_at >= %(t)s)) AS category_queue
"""
OWN_TABLE_SQL = """
SELECT o.arrivals_24h, o.breach_rate_7d, c.category_queue
FROM feast_spike.operations_hourly o
JOIN feast_spike.category_hourly c USING (event_timestamp)
WHERE c.category = %(c)s AND o.event_timestamp <= %(t)s
ORDER BY o.event_timestamp DESC
LIMIT 1
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def latency_ms(fn, calls: int) -> dict[str, float]:
    fn()  # calentamiento: conexiones y cachés
    samples = []
    for _ in range(calls):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    q = statistics.quantiles(samples, n=100)
    return {"p50_ms": statistics.median(samples), "p95_ms": q[94], "p99_ms": q[98]}


def footprint() -> dict:
    venv = Path(sys.prefix)
    size = subprocess.run(["du", "-sm", str(venv)], capture_output=True, text=True).stdout
    import_s = subprocess.run(
        [sys.executable, "-c", "import time; s=time.time(); import feast; print(time.time()-s)"],
        capture_output=True,
        text=True,
        env=os.environ,
    ).stdout
    config_lines = sum(
        len(p.read_text().splitlines())
        for p in (REPO / "feature_store.yaml", REPO / "definitions.py")
    )
    return {
        "feast_version": metadata.version("feast"),
        "pandas_version": metadata.version("pandas"),
        "packages": len(list(metadata.distributions())),
        "venv_mb": int(size.split()[0]),
        "import_feast_s": float(import_s.strip()),
        "feast_config_lines": config_lines,
    }


def parity(retrieved: pd.DataFrame, expected: pd.DataFrame, prefix: str) -> dict:
    merged = retrieved.merge(expected, on="ticket_id", validate="one_to_one")
    out = {}
    for name in NAMES:
        got = merged[name].astype(float)
        want = merged[f"{prefix}_{name}"].astype(float)
        diff = (got - want).abs()
        out[name] = {
            "rows": len(merged),
            "nulls": int(got.isna().sum()),
            "equal": int((diff < 1e-12).sum()),
            "mean_abs_diff": float(diff.mean()),
            "max_abs_diff": float(diff.max()),
        }
    return out


def main() -> int:
    report: dict = {"footprint": footprint()}
    store = FeatureStore(repo_path=str(REPO))
    _, report["apply_s"] = timed(
        lambda: store.apply([team, category, operations, category_context])
    )

    with connect() as conn:
        expected = pd.read_sql("SELECT * FROM feast_spike.expected", conn)
        last_hour = pd.read_sql(
            "SELECT max(event_timestamp) AS t FROM feast_spike.operations_hourly", conn
        )["t"][0]
    expected["ticket_id"] = expected["ticket_id"].astype(str)
    entity_df = pd.DataFrame(
        {
            "ticket_id": expected["ticket_id"],
            "category": expected["category"],
            "team": "support",
            "event_timestamp": pd.to_datetime(expected["created_at"], utc=True),
        }
    )

    historical, report["historical_s"] = timed(
        lambda: store.get_historical_features(entity_df=entity_df, features=FEATURES).to_df()
    )
    report["parity_vs_hourly"] = parity(historical, expected, "hourly")
    report["staleness_vs_exact"] = parity(historical, expected, "exact")

    start = pd.Timestamp(expected["created_at"].min()).to_pydatetime() - timedelta(hours=1)
    end = pd.Timestamp(last_hour).to_pydatetime() + timedelta(minutes=1)
    _, report["materialize_s"] = timed(lambda: store.materialize(start, end))

    def online(cat: str = "network") -> dict:
        return store.get_online_features(
            features=FEATURES, entity_rows=[{"category": cat, "team": "support"}]
        ).to_dict()

    online_values = {cat: online(cat) for cat in ("billing", "network", "account")}
    report["online_values"] = online_values
    report["online_latency"] = latency_ms(online, ONLINE_CALLS)

    with connect() as conn:

        def on_demand(cat: str = "network") -> tuple:
            return conn.execute(ON_DEMAND_SQL, {"t": last_hour, "c": cat}).fetchone()

        def own_table(cat: str = "network") -> tuple:
            return conn.execute(OWN_TABLE_SQL, {"t": last_hour, "c": cat}).fetchone()

        for name, fn in (("on_demand", on_demand), ("own_table", own_table)):
            report[f"{name}_values"] = {
                cat: dict(zip(NAMES, map(float, fn(cat)), strict=True))
                for cat in ("billing", "network", "account")
            }
            report[f"{name}_latency"] = latency_ms(fn, ONLINE_CALLS)
        hourly = pd.read_sql(
            """SELECT o.arrivals_24h, o.breach_rate_7d, c.category, c.category_queue
               FROM feast_spike.operations_hourly o
               JOIN feast_spike.category_hourly c USING (event_timestamp)
               WHERE event_timestamp = %(t)s""",
            conn,
            params={"t": last_hour},
        )
    report["last_hour"] = str(last_hour)
    report["reference_last_hour"] = hourly.to_dict(orient="records")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "feast_spike.json").write_text(json.dumps(report, indent=2, default=str))
    summary = {k: v for k, v in report.items() if k.endswith(("_s", "latency", "footprint"))}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
