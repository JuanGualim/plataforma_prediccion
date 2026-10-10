# Arquitectura

> **Estado:** esqueleto (fase 1). Este documento crece con cada fase.
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
| PostgreSQL (datos operativos) | `docker-compose.yml`, `infra/postgres` | 1 | Ejecutado (contenedor y esquemas `support`/`monitoring`; sin tablas aún) |
| Configuración y logging | `mlplatform.config`, `mlplatform.logging_config` | 1 | Ejecutado |
| Regla de dependencias plataforma → casos de uso | `tests/unit/test_architecture.py` | 1 | Ejecutado |
| Simulador de tickets | `use_cases.sla_risk` | 1 | Pendiente |
| Entrenamiento y evaluación | `mlplatform.training` | 2 | Pendiente |
| Tracking y registry (MLflow + MinIO) | `mlplatform.registry` | 3 | Pendiente |
| Contrato, puerta de promoción, rollback | `mlplatform.lifecycle` | 3 | Pendiente |
| Serving | `mlplatform.serving` | 4 | Pendiente |
| Monitoreo | `mlplatform.monitoring` | 5 | Pendiente |
| Feature store (Feast) | — | 6 | Pendiente (opcional) |
| Kubernetes local (kind) | `infra/k8s` | 10 | Pendiente |
| Despliegue en nube | — | 10 | Solo diseño (no se ejecutará) |

## Flujos principales

_Por completar en cada fase:_

1. **Entrenamiento:** datos → split temporal → pipeline → evaluación → registro como candidato.
2. **Promoción:** candidato → validación del contrato → comparación con champion → cambio de alias.
3. **Predicción:** request → validación de esquema → modelo champion → respuesta con versión → log de predicción.
4. **Retroalimentación:** llega la etiqueta real → unión con la predicción → métricas del modelo.

## Decisiones

Ver [`adr/`](adr/).
