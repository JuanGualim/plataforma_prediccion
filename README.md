# Plataforma de predicción para soporte técnico

Mini plataforma interna de **MLOps / LLMOps** para un área de soporte técnico. El producto
principal es la **plataforma**: un conjunto de estándares y componentes para que distintos
equipos de Data Science entrenen, registren, desplieguen, monitoreen y retiren modelos de
forma uniforme. Los modelos son sus "clientes" y sirven para probar que la plataforma funciona
con casos de distinta naturaleza.

> **Estado actual:** fase 1 completada: datos sintéticos en PostgreSQL, barrera contra fugas de
> información y baselines del modelo de SLA. Ver la [hoja de ruta](#hoja-de-ruta).

## El problema

En un área de soporte, cada equipo que construye un modelo tiende a resolver por su cuenta
cómo versionarlo, desplegarlo y vigilarlo. El resultado: modelos que nadie sabe con qué datos
se entrenaron, despliegues manuales sin vuelta atrás y caídas de calidad que se descubren
semanas después. Esta plataforma propone un camino común:

- **Contrato de despliegue:** todo modelo declara su firma, model card, métricas, dataset, commit y dependencias.
- **Puerta de promoción:** un candidato solo reemplaza al modelo en producción si es mejor y pasa los chequeos de datos. El rollback es un solo comando.
- **Serving estándar:** misma API para todos los modelos; cada respuesta dice qué versión respondió.
- **Monitoreo en tres niveles:** servicio, datos y modelo.
- **Gobierno:** aprobaciones, manejo de información personal y runbook de incidentes.

## Modelos cliente

| # | Caso de uso | Tipo | Fases |
|---|---|---|---|
| 1 | **Riesgo de incumplir el SLA**: al crear un ticket, probabilidad de que no se resuelva a tiempo | Tabular, scikit-learn | 1–5 |
| 2 | **Enrutamiento de tickets**: categoría o grupo destino a partir del texto | Texto, Hugging Face (posible LoRA) | 7, 9 |
| 3 | **Asistente RAG** sobre manuales de soporte | LLM, prompts versionados | 8 |

## Alcance

- Ciclo de vida completo de un modelo tabular: datos → entrenamiento → registro → promoción → serving → monitoreo → incidente → rollback.
- Experimentos y registro con MLflow (metadatos en PostgreSQL, artefactos en MinIO).
- Serving con FastAPI, empaquetado con Docker Compose y, más adelante, Kubernetes local (kind).
- Comparación de costo y latencia entre variantes de un modelo y costo por consulta del RAG.
- Documentación de arquitectura, decisiones (ADR), estándar de despliegue, gobierno y runbook.

## Fuera del alcance

- **Valor de negocio validado.** Los datos son sintéticos, generados por un simulador documentado (ver [ADR 0003](docs/adr/0003-datos-sinteticos-con-simulador.md)). Las métricas prueban que el sistema funciona, no que el modelo sirva en una empresa real.
- **Despliegue real en la nube.** El mapeo a SageMaker / Vertex AI / Azure ML queda **solo diseñado**.
- Alta disponibilidad, multi-región, autenticación corporativa (SSO) y cumplimiento normativo formal.
- Usar todas las herramientas del ecosistema: se elige cada una con criterio y se documenta cuándo **no** se justifica (por ejemplo, Feast).

## Inicio rápido

Requisitos: [uv](https://docs.astral.sh/uv/), Docker con Compose y `make`.

```bash
make setup             # crea .env, instala Python 3.12 y las dependencias
make test              # pruebas unitarias (incluye las de fuga de información)
make up                # levanta PostgreSQL (puerto 5433 en localhost)
make data              # genera tickets sintéticos, los valida y los carga
make baseline          # evalúa los baselines del modelo de SLA
make test-integration  # pruebas contra PostgreSQL
make help              # lista todos los comandos
```

## Estructura

```
src/mlplatform/    La plataforma (genérica; nunca importa de use_cases)
  data/            Conexión a Postgres, esquemas, validación de datos
  training/        Splits temporales, métricas, selección de umbral
  registry/        Adaptador sobre MLflow (mecanismo)
  lifecycle/       Contrato, puerta de promoción, rollback (política)
  serving/         API FastAPI genérica
  monitoring/      Monitoreo de servicio, datos y modelo
src/use_cases/     Modelos cliente: sla_risk, ticket_routing, support_rag
tests/             unit/ (sin servicios) e integration/ (con docker compose)
infra/             Scripts de Postgres; manifiestos de Kubernetes (fase 10)
docs/              Arquitectura, diccionario de datos, ADR, estándar, gobierno, runbook
```

## Hoja de ruta

Estados: ✅ ejecutado · 🚧 en curso · ⬜ pendiente · 📐 solo diseño

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura, datos (simulador + Postgres), baseline ingenuo, pruebas de fuga | ✅ |
| 2 | Entrenamiento con scikit-learn: pipelines, umbral, métricas para clases desbalanceadas | ⬜ |
| 3 | MLflow: tracking, registro, contrato, puerta de promoción, rollback | ⬜ |
| 4 | Serving con FastAPI y Docker Compose | ⬜ |
| 5 | Monitoreo, simulación de drift, reporte de incidente | ⬜ |
| 6 | Feast (opcional y acotado), con criterios de cuándo no se justifica | ⬜ |
| 7 | Clasificador de texto con PyTorch y Hugging Face | ⬜ |
| 8 | RAG evaluado (retriever y respuestas por separado), costo por consulta | ⬜ |
| 9 | Fine-tuning pequeño con LoRA (limitado por hardware: solo CPU) | ⬜ |
| 10 | Kubernetes local (kind), mapeo a la nube, demostración | ⬜ / 📐 |

## Documentación

- [Arquitectura](docs/architecture.md)
- [Diccionario de datos](docs/data_dictionary.md)
- [Simulador de tickets](docs/simulator.md)
- [Resultados fase 1: baselines](docs/results/fase1_baseline_sla_risk.md)
- [Decisiones técnicas (ADR)](docs/adr/)
- [Estándar de despliegue](docs/deployment_standard.md)
- [Política de gobierno](docs/governance_policy.md)
- [Runbook de incidentes](docs/incident_runbook.md)
