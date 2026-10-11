# Servidor de MLflow con los drivers que la imagen oficial no trae:
# psycopg 3 (metadatos en PostgreSQL; es el driver por defecto de SQLAlchemy 2.1) y
# boto3 (artefactos en almacenamiento S3).
# La versión del servidor debe coincidir con la del cliente (mlflow-skinny en pyproject.toml).
FROM ghcr.io/mlflow/mlflow:v3.17.0

RUN pip install --no-cache-dir "psycopg[binary]==3.3.6" boto3==1.43.111

COPY bootstrap.py /opt/mlflow/bootstrap.py
