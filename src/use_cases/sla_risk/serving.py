"""Serving del modelo de riesgo de SLA sobre la API genérica de la plataforma.

    uvicorn use_cases.sla_risk.serving:app_factory --factory

Solo define lo propio del caso de uso: el esquema de un ticket recién creado y cómo
convertirlo en la tabla que espera el pipeline. Todo lo demás lo pone mlplatform.serving.
"""

from typing import Annotated

import pandas as pd
from fastapi import FastAPI
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from mlplatform.config import get_settings
from mlplatform.logging_config import configure_logging
from mlplatform.serving.app import ServingSpec, create_app
from mlplatform.serving.models import RegistryModelSource
from use_cases.sla_risk.contract import MODEL_NAME
from use_cases.sla_risk.fields import FEATURES

Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class TicketAtCreation(BaseModel):
    """Lo que se sabe de un ticket en el instante en que se crea (T0).

    Las categorías se aceptan como texto libre: un canal nuevo no debe tumbar la predicción
    (el pipeline lo trata como "desconocido"); detectarlo es tarea del monitoreo de datos.
    La fecha debe incluir zona horaria: "08:00" sin zona es ambiguo y cambiaría las features
    de hora del día.
    """

    model_config = ConfigDict(extra="forbid")  # un campo de más (p. ej. resolved_at) es un error

    ticket_id: str | None = Field(default=None, max_length=64, description="solo trazabilidad")
    created_at: AwareDatetime
    channel: Category
    category: Category
    priority: Category
    customer_tier: Category
    product: Category
    sla_hours: int = Field(gt=0, le=24 * 30)
    open_tickets_in_queue: int = Field(ge=0)


def tickets_to_frame(instances: list[TicketAtCreation]) -> pd.DataFrame:
    frame = pd.DataFrame([i.model_dump(exclude={"ticket_id"}) for i in instances])
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True)
    return frame


def positive_class_probability(model, frame: pd.DataFrame):
    return model.predict_proba(frame)[:, 1]


SPEC = ServingSpec(
    model_name=MODEL_NAME,
    instance_model=TicketAtCreation,
    feature_columns=FEATURES,
    to_frame=tickets_to_frame,
    score=positive_class_probability,
    entity_id_field="ticket_id",
)


def app_factory() -> FastAPI:
    # Imports diferidos: MLflow y la base de datos solo se necesitan en el servicio real.
    from mlplatform.data.db import get_engine
    from mlplatform.registry.mlflow_registry import MlflowModelRegistry
    from mlplatform.serving.prediction_log import PostgresPredictionLog

    configure_logging()
    settings = get_settings()
    return create_app(
        SPEC,
        source=RegistryModelSource(MlflowModelRegistry(), MODEL_NAME),
        prediction_log=PostgresPredictionLog(get_engine()),
        refresh_seconds=settings.serving_refresh_seconds,
        max_batch=settings.serving_max_batch,
    )
