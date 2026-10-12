"""API de predicción genérica de la plataforma.

Cada caso de uso aporta un `ServingSpec` (esquema de entrada y cómo puntuar) y la plataforma
pone lo común a todos los modelos:

- /health  -> el proceso está vivo (liveness). Siempre 200 si responde.
- /ready   -> hay un modelo cargado y listo (readiness). 503 si no.
- /metadata-> qué versión sirve, su umbral y su trazabilidad (commit, dataset, métricas).
- /predict -> puntúa un lote; la respuesta SIEMPRE dice qué modelo y versión respondió.

Además: identificador de petición (X-Request-ID), log estructurado con latencia de cada
petición, registro de predicciones y de peticiones (para el monitoreo) y recarga del champion
sin reiniciar.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, create_model

from mlplatform.serving.models import ModelHolder, ModelSource
from mlplatform.serving.prediction_log import (
    PredictionLog,
    PredictionRecord,
    RequestLog,
    RequestRecord,
)

logger = logging.getLogger(__name__)
SYNTHETIC = "synthetic"
REQUEST_LOG_FLUSH_SECONDS = 5


class RequestBuffer:
    """Collects request records in memory and writes them in batches.

    Escribir cada petición por separado sumaría un viaje a la base de datos por llamada; en lote
    cada pocos segundos el costo es mínimo. Si el proceso cae se pierden, como mucho, los
    últimos segundos de registros.
    """

    def __init__(self, log: RequestLog) -> None:
        self.log = log
        self._records: list[RequestRecord] = []
        self._lock = threading.Lock()

    def add(self, record: RequestRecord) -> None:
        with self._lock:
            self._records.append(record)

    def flush(self) -> None:
        with self._lock:
            records, self._records = self._records, []
        self.log.write(records)


@dataclass(frozen=True)
class ServingSpec:
    model_name: str
    instance_model: type[BaseModel]  # esquema de UNA instancia (validado por pydantic)
    feature_columns: list[str]  # columnas que recibe el modelo, en orden (= firma del contrato)
    to_frame: Callable[[list[BaseModel]], pd.DataFrame]
    score: Callable[[Any, pd.DataFrame], np.ndarray]  # probabilidad de la clase positiva
    entity_id_field: str | None = None  # campo identificador opcional (no es feature)


class Prediction(BaseModel):
    entity_id: str | None
    score: float
    decision: bool


class PredictResponse(BaseModel):
    request_id: str
    model_name: str
    model_version: str
    threshold: float
    predictions: list[Prediction]


def create_app(
    spec: ServingSpec,
    source: ModelSource,
    prediction_log: PredictionLog | None = None,
    request_log: RequestLog | None = None,
    refresh_seconds: int = 30,
    max_batch: int = 100,
) -> FastAPI:
    holder = ModelHolder(source, spec.feature_columns)
    requests_buffer = RequestBuffer(request_log) if request_log is not None else None
    non_features = {spec.entity_id_field} if spec.entity_id_field else None

    predict_request = create_model(
        "PredictRequest",
        instances=(
            Annotated[list[spec.instance_model], Field(min_length=1, max_length=max_batch)],
            ...,
        ),
    )

    async def refresh_forever() -> None:
        while True:
            await asyncio.sleep(refresh_seconds)
            await asyncio.to_thread(holder.refresh)

    async def flush_forever() -> None:
        while True:
            await asyncio.sleep(REQUEST_LOG_FLUSH_SECONDS)
            await asyncio.to_thread(requests_buffer.flush)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(holder.refresh)
        tasks = []
        if refresh_seconds > 0:
            tasks.append(asyncio.create_task(refresh_forever()))
        if requests_buffer is not None:
            tasks.append(asyncio.create_task(flush_forever()))
        yield
        for task in tasks:
            task.cancel()
        if requests_buffer is not None:
            requests_buffer.flush()  # no perder los últimos registros al apagar

    app = FastAPI(title=f"Serving: {spec.model_name}", lifespan=lifespan)
    app.state.holder = holder
    app.state.requests_buffer = requests_buffer

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        # Tráfico de prueba se declara con `X-Traffic-Source: synthetic`; el resto es real.
        declared = request.headers.get("x-traffic-source", "").strip().lower()
        request.state.traffic_source = SYNTHETIC if declared == SYNTHETIC else "live"
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = request_id
        if requests_buffer is not None and request.url.path == "/predict":
            requests_buffer.add(
                RequestRecord(
                    request_id=request_id,
                    path=request.url.path,
                    status=response.status_code,
                    latency_ms=elapsed_ms,
                    model_version=getattr(request.state, "model_version", None),
                    traffic_source=request.state.traffic_source,
                    requested_at=datetime.now(UTC).isoformat(),
                )
            )
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round(elapsed_ms, 2),
                "traffic_source": request.state.traffic_source,
            },
        )
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        bundle = holder.bundle
        if bundle is None:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "reason": holder.last_error}
            )
        return JSONResponse({"status": "ready", "model_version": bundle.version})

    @app.get("/metadata")
    def metadata() -> dict:
        bundle = holder.bundle
        if bundle is None:
            raise HTTPException(503, detail=holder.last_error or "model not loaded")
        contract = bundle.contract
        return {
            "model_name": bundle.name,
            "model_version": bundle.version,
            "alias": "champion",
            "loaded_at": bundle.loaded_at,
            "threshold": contract.threshold.model_dump(),
            "inputs": [f.model_dump() for f in contract.signature.inputs],
            "output": contract.signature.output,
            "primary_metric": contract.primary_metric,
            "test_metrics": contract.test_metrics,
            "trained_from": {
                "git_commit": contract.code.git_commit,
                "dataset_fingerprint": contract.dataset.fingerprint,
                "data_end": contract.dataset.data_end,
                "contract_created_at": contract.created_at,
            },
            "refresh_seconds": refresh_seconds,
            "last_refresh_error": holder.last_error,
        }

    @app.post("/predict", response_model=PredictResponse)
    def predict(body: predict_request, request: Request, background: BackgroundTasks):  # type: ignore[valid-type]
        bundle = holder.bundle  # una sola lectura: toda la petición usa la misma versión
        if bundle is None:
            raise HTTPException(503, detail=holder.last_error or "model not loaded")
        request.state.model_version = bundle.version

        start = time.perf_counter()
        frame = spec.to_frame(body.instances)[spec.feature_columns]
        scores = np.asarray(spec.score(bundle.model, frame), dtype=float)
        latency_ms = (time.perf_counter() - start) * 1000

        threshold = bundle.contract.threshold.value
        ids = [
            getattr(i, spec.entity_id_field) if spec.entity_id_field else None
            for i in body.instances
        ]
        predictions = [
            Prediction(entity_id=entity, score=float(s), decision=bool(s >= threshold))
            for entity, s in zip(ids, scores, strict=True)
        ]

        if prediction_log is not None:
            now = datetime.now(UTC).isoformat()
            records = [
                PredictionRecord(
                    prediction_id=str(uuid.uuid4()),
                    request_id=request.state.request_id,
                    entity_id=p.entity_id,
                    model_name=bundle.name,
                    model_version=bundle.version,
                    score=p.score,
                    decision=p.decision,
                    threshold=threshold,
                    features=instance.model_dump(mode="json", exclude=non_features),
                    predicted_at=now,
                    latency_ms=latency_ms / len(predictions),
                    traffic_source=request.state.traffic_source,
                )
                for p, instance in zip(predictions, body.instances, strict=True)
            ]
            # Se escribe DESPUÉS de responder: el cliente no espera a la base de datos.
            background.add_task(prediction_log.write, records)

        return PredictResponse(
            request_id=request.state.request_id,
            model_name=bundle.name,
            model_version=bundle.version,
            threshold=threshold,
            predictions=predictions,
        )

    return app
