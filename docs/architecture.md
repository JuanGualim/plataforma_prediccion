# Arquitectura

> **Estado:** fases 1 a 5 completadas. Este documento crece con cada fase.
> Convención de honestidad: cada componente se marca como **Ejecutado** (corre y está
> probado en este repositorio) o **Diseñado** (solo documentado; no se ha ejecutado).

## Vista general (objetivo)

```
                 ┌──────────────────────── use_cases/ (equipos cliente) ───────────────────────┐
                 │  sla_risk (tabular)     ticket_routing (texto)      support_rag (LLM)       │
                 └───────────────┬─────────────────────────────────────────────────────────────┘
                                 │ usan (nunca al revés)
┌────────────────────────────────▼──────────────────── mlplatform/ ───────────────────────────────┐
│  data ──► training ──► registry (MLflow) ◄── lifecycle (contrato + puerta + rollback)            │
│                              │                                                                   │
│                              ▼ alias "champion"                                                  │
│                          serving (FastAPI) ──► monitoring (servicio · datos · modelo)            │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
        │                         │                               │
   PostgreSQL              MLflow + SeaweedFS               Logs / métricas
 (tickets, eventos,     (metadatos en Postgres,
  auditoría)             artefactos S3 vía proxy)
```

## Componentes y estado

| Componente | Módulo | Fase | Estado |
|---|---|---|---|
| PostgreSQL (datos operativos) | `docker-compose.yml`, `infra/postgres`, `use_cases.sla_risk.storage` | 1 | Ejecutado (tablas `tickets` y `ticket_events`, carga con COPY) |
| Configuración y logging | `mlplatform.config`, `mlplatform.logging_config` | 1 | Ejecutado |
| Regla de dependencias plataforma → casos de uso | `tests/unit/test_architecture.py` | 1 | Ejecutado |
| Catálogo de campos y barrera contra fugas | `mlplatform.data.catalog`, `use_cases.sla_risk.fields` | 1 | Ejecutado |
| Validación de datos | `mlplatform.data.validation` | 1 | Ejecutado |
| Simulador de tickets | `use_cases.sla_risk.simulator` | 1 | Ejecutado |
| Split temporal con madurez de etiquetas | `mlplatform.training.splits`, `use_cases.sla_risk.dataset` | 1 | Ejecutado (ampliado en fase 2) |
| Métricas y baselines | `mlplatform.training.metrics`, `mlplatform.training.baselines` | 1 | Ejecutado |
| CI (lint + pruebas + integración con el stack completo) | `.github/workflows/ci.yml` | 1-3 | Diseñado (no se ha ejecutado en GitHub) |
| Split temporal train / validation / test | `use_cases.sla_risk.dataset` | 2 | Ejecutado |
| Pipelines de scikit-learn (preprocesamiento dentro del artefacto) | `use_cases.sla_risk.features`, `.models` | 2 | Ejecutado |
| Selección de candidatos y umbral por costo | `mlplatform.training.selection`, `.thresholds` | 2 | Ejecutado |
| Calibración, segmentos e importancia por permutación | `mlplatform.training.metrics`, `use_cases.sla_risk.train` | 2 | Ejecutado |
| Trazabilidad (commit + entorno + lockfile + huella del dataset) | `mlplatform.training.lineage`, `mlplatform.data.fingerprint` | 2-3 | Ejecutado |
| Tracking y registry (MLflow 3.17 + SeaweedFS) | `docker-compose.yml`, `infra/mlflow`, `mlplatform.registry.mlflow_registry` | 3 | Ejecutado |
| Contrato de despliegue y model card | `mlplatform.lifecycle.contract`, `use_cases.sla_risk.contract`, `.model_card` | 3 | Ejecutado |
| Puerta de promoción y rollback | `mlplatform.lifecycle.promotion`, `.service`, `use_cases.sla_risk.registry_cli` | 3 | Ejecutado |
| Bitácora de auditoría | `mlplatform.registry.event_log` (`governance.model_events`) | 3 | Ejecutado |
| Serving genérico (FastAPI: /health, /ready, /metadata, /predict) | `mlplatform.serving.app`, `.models` | 4 | Ejecutado |
| Serving del modelo de SLA (esquema de entrada) | `use_cases.sla_risk.serving` | 4 | Ejecutado |
| Recarga del champion sin reiniciar | `mlplatform.serving.models.ModelHolder` | 4 | Ejecutado (0 errores en promoción + rollback con tráfico) |
| Registro de predicciones | `mlplatform.serving.prediction_log` (`monitoring.predictions`) | 4 | Ejecutado |
| Imagen de serving y servicio en Compose | `infra/serving/Dockerfile`, `docker-compose.yml` | 4 | Ejecutado |
| Registro de peticiones (servicio) | `mlplatform.serving` (`monitoring.requests`, escritura por lotes) | 5 | Ejecutado |
| Perfil de referencia por versión | `mlplatform.monitoring.drift`, `use_cases.sla_risk.monitoring` | 5 | Ejecutado (`reference_profile.json` en MLflow) |
| Monitoreo en tres niveles y reglas de alerta | `mlplatform.monitoring` (`service`, `drift`, `performance`, `rules`) | 5 | Ejecutado (reporte por lotes; ejecución programada: fase 10) |
| Tráfico de producción simulado y reporte | `use_cases.sla_risk.replay`, `.monitor` | 5 | Ejecutado (incidente INC-001) |
| Paneles en tiempo real (Prometheus / Grafana) | — | 10 | Solo diseño |
| Feature store (Feast) | — | 6 | Pendiente (opcional) |
| Kubernetes local (kind) | `infra/k8s` | 10 | Pendiente |
| Despliegue en nube | — | 10 | Solo diseño (no se ejecutará) |

## Flujos principales

1. **Datos (fase 1, ejecutado):** simulador → validación contra el catálogo → carga atómica en
   `support.tickets` / `support.ticket_events` (`make data`).
2. **Evaluación de baselines (fase 1, ejecutado):** lectura de Postgres → split temporal con fecha de
   corte → filas con etiqueta conocida en el corte → `select_features` (barrera de fugas) →
   baselines → reporte JSON (`make baseline`).

3. **Entrenamiento (fase 2, ejecutado):** lectura de Postgres → train / validation / test temporales
   → candidatos (pipelines) entrenados en train → selección en validation → umbral por costo en
   validation → evaluación única en test contra el baseline → `model.joblib` + `report.json` (`make train`).

4. **Registro (fase 3, ejecutado):** el entrenamiento construye el contrato y la model card y los
   registra en MLflow como versión `candidate`, con un run hijo por candidato.
5. **Promoción (fase 3, ejecutado):** `make promote` → candidato, champion y baseline reevaluados en la
   misma ventana → puerta → alias `champion` + tags + evento en `governance.model_events`.
6. **Rollback (fase 3, ejecutado):** `make rollback REASON=...` → alias a la versión anterior + evento.

7. **Predicción (fase 4, ejecutado):** request → validación pydantic (esquema = firma del contrato) →
   modelo `@champion` en memoria → respuesta con versión y umbral → registro en `monitoring.predictions`
   después de responder. El servicio consulta el alias cada 15 s y cambia de versión sin reiniciar.

8. **Monitoreo (fase 5, ejecutado):** `make monitor` → predicciones `live` de la versión por fecha del
   evento → (a) servicio desde `monitoring.requests`; (b) PSI contra el `reference_profile.json` de esa
   versión; (c) unión con `support.tickets` cuando llega el resultado real → métricas vs. contrato →
   hallazgos con severidad y escenario del runbook → reporte Markdown + JSON.
9. **Incidente (fase 5, ejecutado):** hallazgo → runbook (B/C) → rollback (D) o reentrenamiento →
   puerta → verificación con `make monitor`. Ejemplo completo: [INC-001](incidents/INC-001-drift-carga-sla-risk.md).

## Decisiones

Ver [`adr/`](adr/).
