# Fase 4: serving del modelo de SLA (demostración)

> **Estado:** Ejecutado el 2026-10-11 con `make serve` en Docker Compose (laptop de desarrollo: 8 núcleos,
> 15 GB de RAM, sin GPU). **Las latencias son mediciones locales de referencia, no un benchmark de
> capacidad.** Datos sintéticos.

## 1. La API en uso

```bash
$ make serve
{"status":"ready","model_version":"1"}

$ make predict-example
{"request_id":"67c5…","model_name":"sla_risk","model_version":"1","threshold":0.16,
 "predictions":[{"entity_id":"EJEMPLO-ALTO-RIESGO","score":0.935,"decision":true},
                {"entity_id":"EJEMPLO-BAJO-RIESGO","score":0.005,"decision":false}]}
```

- Ticket de alto riesgo: email, hardware, cliente enterprise, creado a las 19:30, cola de 140.
- Ticket de bajo riesgo: teléfono, cuenta, prioridad alta, cola de 60.

`GET /metadata` devuelve la versión, el umbral con sus costos, la firma de entrada, las métricas de
prueba, el commit, la huella del dataset y el último error de recarga, si lo hubo.

## 2. Validación de entrada

```json
{"created_at": "2025-08-04T09:00:00", ..., "resolved_at": "2025-08-05T09:00:00-05:00"}
→ 422
  created_at  -> Input should have timezone info
  resolved_at -> Extra inputs are not permitted
```

`resolved_at` es un dato del futuro: el esquema de la API también aplica la regla "el momento de la
predicción es sagrado". Un canal desconocido (`whatsapp`), en cambio, **sí se sirve**.

## 3. Latencia (`make latency`, peticiones secuenciales, medidas desde el cliente)

| Carga por petición | p50 | p95 | p99 | Peticiones/s |
|---|---|---|---|---|
| 2 tickets (300 peticiones) | 32,0 ms | 39,3 ms | 46,2 ms | 29,9 |
| 100 tickets (100 peticiones) | 65,8 ms | 75,8 ms | 87,5 ms | 14,9 |

Desglose con los tiempos que el servicio guarda en `monitoring.predictions`:

| Carga | p50 dentro del servicio (tabla + pipeline) | Resto (HTTP, JSON, red local) |
|---|---|---|
| 2 tickets | 25,1 ms | ~7 ms |
| 100 tickets | 38,6 ms | ~27 ms |

**Lectura:** casi todo el costo es **fijo por petición**. Armar el DataFrame y pasar por el
`ColumnTransformer` cuesta ~25 ms con 2 filas o con 100. Por ticket, un lote de 100 cuesta 0,66 ms y una
petición de 2 tickets, 16 ms. Para puntuar en volumen conviene agrupar. Hay espacio de optimización
(ONNX, evitar la salida en pandas), que se aborda en la fase de costo y latencia.

## 4. Cambio de champion en caliente, con tráfico continuo

Se envió una petición cada 0,2 s durante 110 s mientras se promovía la v3 y luego se revertía:

| Instante | Evento | Versión servida |
|---|---|---|
| t = 0 s | `make promote VERSION=3` (APPROVED, termina en t = 9,7 s) | v1 |
| t = 10,1 s | el servicio detecta el nuevo alias | **v3** |
| t = 34,7 s | `make rollback REASON=...` (termina en t = 40,5 s) | v3 |
| t = 41,0 s | el servicio detecta el alias restaurado | **v1** |

**471 peticiones, 0 errores.** El cambio llegó en menos de 1 s porque la consulta coincidió; el peor
caso es el intervalo de consulta (15 s) más la carga del modelo.

## 5. Incidentes reales durante la implementación

| Síntoma | Causa | Solución | Lección |
|---|---|---|---|
| `/ready` = 503: *"Invalid Host header - possible DNS rebinding attack"* | MLflow solo acepta los encabezados `Host` que conoce, y `mlflow:5000` (el nombre interno) no estaba en su lista | `--allowed-hosts localhost:*,127.0.0.1:*,mlflow:5000` (un `Host` desconocido sigue recibiendo 403) | El servicio **se recuperó solo**, sin reiniciarlo, en la siguiente consulta: el diseño de readiness y recarga funcionó |
| `make train` falla: MLflow responde 500 al subir artefactos | **El disco del equipo estaba al 100 %**; SeaweedFS no tenía volúmenes escribibles | Se borraron imágenes de prueba propias del proyecto (~444 MB); el resto requiere liberar espacio | El registro de modelos depende del almacenamiento; quedó en el runbook (escenario E) |
| La v1 aparecía con 94,7 % de alertas | 12.000 de 12.567 predicciones eran de la prueba de carga (100 copias del ticket de alto riesgo) | Header `X-Traffic-Source: synthetic` y columna `traffic_source`; las filas previas se marcaron como sintéticas | Sin separar el tráfico de prueba, el monitoreo de la fase 5 habría reportado un drift falso |

## 6. Tamaño de la imagen

`mlplatform-serving:dev` pesa 859 MB: la base `python:3.12-slim` (179 MB) más un entorno de 507 MB. Lo
dominan scipy (109 MB), pandas (72 MB), scikit-learn (49 MB) y numpy (43 MB), todos necesarios para el
pipeline actual. Una variante ONNX podría prescindir de gran parte (fase de optimización).

## 7. Registro de predicciones

Cada predicción queda en `monitoring.predictions` con su versión, puntaje, decisión, umbral,
entradas (sin `ticket_id` ni texto libre), latencia y origen (`live` o `synthetic`). Es la materia
prima de la fase 5: drift de entradas, distribución de puntajes y desempeño real cuando llegue el resultado.
