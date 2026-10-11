# Arquitectura

> **Estado:** fases 1 y 2 completadas. Este documento crece con cada fase.
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
   PostgreSQL               MLflow + MinIO                  Logs / métricas
 (tickets, eventos,     (metadatos en Postgres,
  predicciones)          artefactos en MinIO)
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
| CI (lint + pruebas) | `.github/workflows/ci.yml` | 1 | Diseñado (no se ha ejecutado en GitHub) |
| Split temporal train / validation / test | `use_cases.sla_risk.dataset` | 2 | Ejecutado |
| Pipelines de scikit-learn (preprocesamiento dentro del artefacto) | `use_cases.sla_risk.features`, `.models` | 2 | Ejecutado |
| Selección de candidatos y umbral por costo | `mlplatform.training.selection`, `.thresholds` | 2 | Ejecutado |
| Calibración, segmentos e importancia por permutación | `mlplatform.training.metrics`, `use_cases.sla_risk.train` | 2 | Ejecutado |
| Trazabilidad (commit + entorno) del entrenamiento | `mlplatform.training.lineage` | 2 | Ejecutado (en JSON; MLflow en la fase 3) |
| Tracking y registry (MLflow + MinIO) | `mlplatform.registry` | 3 | Pendiente |
| Contrato, puerta de promoción, rollback | `mlplatform.lifecycle` | 3 | Pendiente |
| Serving | `mlplatform.serving` | 4 | Pendiente |
| Monitoreo | `mlplatform.monitoring` | 5 | Pendiente |
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

_Por completar en las siguientes fases:_

1. **Registro:** el resultado del entrenamiento se registra en MLflow como candidato.
2. **Promoción:** candidato → validación del contrato → comparación con champion → cambio de alias.
3. **Predicción:** request → validación de esquema → modelo champion → respuesta con versión → log de predicción.
4. **Retroalimentación:** llega la etiqueta real → unión con la predicción → métricas del modelo.

## Decisiones

Ver [`adr/`](adr/).
