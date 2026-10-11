# Estándar de despliegue

> **Estado:** Ejecutado (fases 3 y 4). Implementado en `mlplatform.lifecycle` (política),
> `mlplatform.registry` (MLflow y bitácora) y `mlplatform.serving` (API). Probado con dobles en memoria y
> contra el stack real.

Este documento define qué debe cumplir **cualquier** modelo para desplegarse en la plataforma, sin
importar el equipo ni el tipo de modelo.

## 1. Contrato del modelo (obligatorio)

Cada versión registrada guarda un `contract.json` (esquema `DeploymentContract`):

| Elemento | Qué contiene | Cómo se verifica |
|---|---|---|
| Firma de entrada/salida | Columnas de entrada con su tipo; descripción de la salida | pydantic: al menos una entrada. MLflow guarda además su propia firma y un ejemplo de entrada |
| Model card | Markdown con secciones obligatorias: Propósito · Uso previsto y fuera de alcance · Datos · Métricas · Umbral de decisión · Limitaciones · Responsable | `contract_violations`: deben estar todas las secciones |
| Métricas | Validación y prueba del modelo, y prueba del baseline | Debe existir la métrica principal en validación y en prueba |
| Umbral de decisión | Valor en (0, 1), criterio, conjunto donde se eligió (siempre validación) y costos usados | pydantic (rango y conjunto permitido) |
| Referencia al dataset | Fuente, huella sha256 del contenido, rango de fechas, cortes de entrenamiento y validación, filas por conjunto | pydantic: la huella debe tener 64 caracteres hexadecimales |
| Código | Commit de git y si había cambios sin commitear | Política: commit conocido y **sin cambios pendientes** |
| Dependencias | sha256 de `uv.lock` y versiones clave | pydantic: hash completo |
| Chequeos de datos | Resultado de validar la tabla de entrenamiento contra el catálogo | Política: deben haber pasado |

Un contrato estructuralmente incompleto **no se puede construir**. Uno con violaciones de política sí
se registra (queda trazado, con el tag `contract_violations`), pero **no puede promoverse**.

## 2. Estados y alias

| Estado (tag `status`) | Significado |
|---|---|
| `candidate` | Registrado tras entrenar; aún no evaluado por la puerta |
| `champion` | Versión en producción; además tiene el **alias `champion`** (hay uno solo por modelo) |
| `rejected` | La puerta lo rechazó |
| `archived` | Fue champion y lo reemplazó otra versión aprobada |
| `rolled_back` | Fue champion y se revirtió por un incidente |

El serving carga siempre `models:/<modelo>@champion` (sección 6).

## 3. Puerta de promoción (`make promote`)

Candidato, champion y baseline se reevalúan **sobre la misma ventana** (la de prueba del candidato),
con los datos actuales. Aprueba solo si se cumplen **todos** los chequeos:

| Chequeo | Regla por defecto |
|---|---|
| `contract` | Sin violaciones de política |
| `unseen_evaluation_window` | La ventana empieza después de todo lo que ambos modelos usaron (entrenamiento y validación) |
| `beats_baseline` | Métrica principal (PR-AUC) del candidato > baseline |
| `vs_champion` | PR-AUC del candidato ≥ PR-AUC del champion + `min_improvement` (0) |
| `guardrail_brier` | Brier del candidato ≤ champion + 0,005 |
| `guardrail_cost_per_ticket` | Costo por ticket del candidato ≤ champion + 0,01 |

Sin champion (primera promoción), solo aplican los tres primeros.

## 4. Rollback (`make rollback REASON="..."`)

- Un solo comando devuelve el alias `champion` a la versión que lo era antes de la promoción vigente.
- **Exige un motivo** y no pasa por la puerta (la versión destino ya fue aprobada antes).
- Si no hay versión anterior, falla con un mensaje claro en lugar de dejar el registry inconsistente.

## 5. Auditoría

Cada promoción, rechazo y rollback se agrega a `governance.model_events` (PostgreSQL, solo inserción)
con actor, motivo, versiones de origen y destino, y la evaluación completa en JSON. `make models`
muestra las versiones y los últimos eventos.

## 6. Serving (fase 4)

Todo modelo se sirve con `mlplatform.serving` (ver [ADR 0008](adr/0008-serving-generico-con-fastapi.md)):

| Endpoint | Contrato |
|---|---|
| `GET /health` | 200 si el proceso vive (liveness) |
| `GET /ready` | 200 con la versión cargada; 503 con el motivo si no hay modelo (readiness) |
| `GET /metadata` | Versión, umbral, firma, métricas de prueba, commit y huella del dataset |
| `POST /predict` | Lote de 1 a `SERVING_MAX_BATCH` instancias; la respuesta incluye `model_name`, `model_version`, `threshold` y `request_id` |

Reglas:
- Se sirve siempre `models:/<modelo>@champion`. Un cambio de alias se aplica sin reiniciar (consulta
  cada `SERVING_REFRESH_SECONDS`).
- El esquema de la API debe coincidir con la firma del contrato. Si no, el servicio **no carga** ese modelo.
- El umbral se lee del contrato de la versión servida, nunca del código del servicio.
- Toda predicción se registra en `monitoring.predictions`. El tráfico de prueba debe enviar
  `X-Traffic-Source: synthetic`.
