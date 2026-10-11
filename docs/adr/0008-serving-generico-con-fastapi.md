# ADR 0008: Serving genérico con FastAPI, recarga del champion por consulta y registro de predicciones

- **Estado:** Aceptada
- **Fecha:** 2026-10-11
- **Fase:** 4

## Contexto

El modelo champion debe atender peticiones en línea con una API estándar para todos los casos de uso.
La API debe indicar qué versión respondió, seguir los cambios del registry (promoción y rollback) sin
intervención manual y dejar registro de cada predicción para el monitoreo.

## Decisión

1. **FastAPI en `mlplatform.serving`**, genérico. Cada caso de uso aporta un `ServingSpec`: el esquema
   pydantic de una instancia, la conversión a tabla y la función de puntaje. El de SLA ocupa unas 60
   líneas (`use_cases/sla_risk/serving.py`).
2. **Liveness y readiness separados.** `/health` responde si el proceso vive; `/ready` responde 503
   hasta que haya un champion cargado e indica el motivo. Docker usa `/health`, para que el contenedor
   no se reinicie en bucle mientras aún no hay modelo. En Kubernetes (fase 10) se mapean a
   `livenessProbe` y `readinessProbe`.
3. **Recarga por consulta del alias.** El servicio pregunta cada `SERVING_REFRESH_SECONDS` (15 s en
   Compose) qué versión tiene `champion`. Si cambió, carga la nueva y la reemplaza con una sola
   asignación. Si la carga falla, sigue sirviendo la anterior. Además se niega a cargar un modelo cuyo
   contrato no coincide con el esquema de la API.
4. **El esquema de entrada es el contrato:**
   - `extra="forbid"`: un campo como `resolved_at` es un error, no un dato que se ignora en silencio;
   - la fecha debe traer zona horaria;
   - las categorías nuevas se aceptan (el pipeline las trata como desconocidas; detectarlas es
     trabajo del monitoreo).
5. **Registro de predicciones en segundo plano** (`BackgroundTasks`) en `monitoring.predictions`, con
   entradas, puntaje, decisión, versión, latencia y origen del tráfico. Es "mejor esfuerzo": si falla,
   se registra el error pero la predicción ya entregada no se convierte en un error.
6. **Tráfico sintético marcado** con `X-Traffic-Source: synthetic` (pruebas de carga, ejemplos, tests).
7. **Una sola imagen** con el paquete completo, construida con `uv` desde `uv.lock`, en dos etapas y
   con un usuario sin privilegios.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| `mlflow models serve` | Rápido, pero sin `/ready` con motivo, sin recarga por alias, sin registro de predicciones ni validación propia |
| BentoML | Buen empaquetado, pero agrega su propio formato de artefacto y su runtime; aquí el registry ya es MLflow |
| Seldon Core / KServe | Requieren Kubernetes; se revisan en la fase 10 |
| Ray Serve | Útil para escalar o encadenar modelos; excesivo para un modelo de ~25 ms por petición |
| Recargar reiniciando el contenedor | Corta el servicio y requiere un orquestador que reaccione al registry |
| Notificación del registry al serving (webhook) | Más inmediata, pero MLflow OSS no tiene webhooks de alias y acopla ambos sistemas |
| Registro síncrono de predicciones | Suma la latencia de la base de datos a cada respuesta |
| Cola de mensajes (Kafka o Redis) para el registro | Más robusta si el proceso cae, pero es infraestructura que no se justifica todavía |
| Rechazar categorías no vistas (422) | Un canal nuevo tumbaría el servicio; mejor servir y alertar |
| Imagen de serving mínima (sin SQLAlchemy ni pipeline de entrenamiento) | Menor tamaño, pero exige separar el paquete; se revisa con la variante ONNX |

## Consecuencias

- Positivas:
  - En la demostración se hicieron una promoción y un rollback con tráfico continuo: **0 errores en 471 peticiones**.
  - La API y el pipeline dan el mismo puntaje, al bit (probado).
  - Un segundo caso de uso solo debe escribir su `ServingSpec`.
- Negativas:
  - El cambio de versión puede tardar hasta un intervalo de consulta (15 s).
  - Si el proceso cae justo después de responder, se pierden esos registros de predicción.
  - La imagen pesa 859 MB, dominada por scipy, pandas y scikit-learn.
- Reconsiderar si:
  - se requiere un cambio instantáneo de versión (notificación);
  - el registro de predicciones debe ser garantizado (cola);
  - el costo de cómputo o de imagen importa (ONNX, fase de optimización).
