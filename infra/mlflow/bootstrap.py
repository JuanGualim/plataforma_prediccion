"""Crea la base de datos de MLflow si no existe y luego arranca el servidor.

Los scripts de /docker-entrypoint-initdb.d de Postgres solo corren con un volumen vacío;
este paso es idempotente y funciona también sobre un volumen que ya tenía datos.
"""

import os

import psycopg
from psycopg import sql

DB_NAME = os.environ.get("MLFLOW_DB", "mlflow")

# autocommit: CREATE DATABASE no puede ejecutarse dentro de una transacción.
conn = psycopg.connect(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ.get("POSTGRES_PORT", "5432"),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    autocommit=True,
)
with conn.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if cursor.fetchone() is None:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
        print(f"created database {DB_NAME}", flush=True)
conn.close()

backend = (
    f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ['POSTGRES_HOST']}:{os.environ.get('POSTGRES_PORT', '5432')}/{DB_NAME}"
)
os.execvp(
    "mlflow",
    [
        "mlflow",
        "server",
        "--backend-store-uri",
        backend,
        # El servidor hace de intermediario para los artefactos: los clientes solo necesitan
        # la URL de MLflow, nunca las credenciales del almacenamiento.
        "--serve-artifacts",
        "--artifacts-destination",
        os.environ.get("MLFLOW_ARTIFACTS_DESTINATION", "s3://mlflow"),
        "--host",
        "0.0.0.0",
        "--port",
        "5000",
    ],
)
