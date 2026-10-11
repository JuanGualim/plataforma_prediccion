"""Configuración central leída de variables de entorno (y de `.env` si existe).

Un único objeto `Settings` evita que cada módulo lea `os.environ` por su cuenta
y valida tipos al arrancar: un puerto mal escrito falla aquí y no en mitad de un
entrenamiento.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "prod"] = "local"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "support"
    postgres_user: str = "mlplatform"
    # SecretStr evita que la contraseña aparezca al imprimir o loguear Settings.
    postgres_password: SecretStr = SecretStr("mlplatform_local")

    # MLflow: tracking + model registry. Los artefactos pasan siempre por el servidor
    # (modo proxy), así los clientes no necesitan credenciales del almacenamiento.
    mlflow_tracking_uri: str = "http://localhost:5000"

    # Serving: cada cuántos segundos se revisa si cambió el champion (0 = nunca) y tamaño
    # máximo de un lote de predicción.
    serving_refresh_seconds: int = 30
    serving_max_batch: int = 100

    @property
    def database_url(self) -> str:
        """URL de SQLAlchemy usando el driver psycopg 3."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (se construye una sola vez por proceso)."""
    return Settings()
