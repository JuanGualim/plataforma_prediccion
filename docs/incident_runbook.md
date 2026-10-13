# Runbook de incidentes

> **Estado:** Ejecutado. Rollback (D) en la fase 3; caída del servicio (A) y almacenamiento lleno (E)
> en la fase 4; drift (B, C) en la fase 5 con el incidente simulado
> [INC-001](incidents/INC-001-drift-carga-sla-risk.md). Los tiempos de respuesta son una propuesta:
> no hay un equipo de guardia real.

## Severidades

| Nivel | Criterio | Tiempo de respuesta objetivo |
|---|---|---|
| SEV1 | El servicio de predicción no responde o devuelve errores masivos (5xx > 1 %) | Inmediato (propuesta: 15 min) |
| SEV2 | El servicio responde, pero la calidad del modelo está degradada (confirmado con etiquetas reales) | Mismo día hábil |
| SEV3 | Señal temprana (drift de datos o de puntajes, categoría nueva, p95 alto) sin impacto confirmado | Siguiente revisión semanal |

Las reglas que asignan la severidad están en `mlplatform.monitoring.rules`; cada hallazgo del reporte
trae la letra del escenario de este runbook.

## Primeros pasos (cualquier incidente)

1. ¿Qué versión está sirviendo? → `curl localhost:8000/metadata` y `make models` (alias `champion`)
2. ¿Cambió algo recientemente? → `make models` muestra los últimos eventos de `governance.model_events`
3. ¿Es un problema del servicio, de los datos o del modelo? → `make monitor ARGS="--from <fecha> --to <fecha>"`
   (reporte en `data/reports/monitoring/`, con hallazgos, PSI por variable, métricas reales y evolución semanal)

## Escenarios

### A. El servicio no responde, no está listo o está lento
- **Síntomas:** errores 5xx o *timeouts* en los clientes; `/ready` responde 503; latencia alta en el log.
- **Diagnóstico:**
  1. `docker compose ps`: ¿`mlplatform-serving` está `healthy`? Si no, el proceso cayó: revisar
     `docker logs mlplatform-serving`.
  2. `curl localhost:8000/ready`: si es 503, el campo `reason` dice por qué. Casos vistos:
     - *"no champion registered yet"*: nadie ha promovido un modelo → `make promote`.
     - *"Invalid Host header"*: MLflow rechaza el nombre del servicio → revisar `MLFLOW_ALLOWED_HOSTS`.
     - *"cannot load version N"*: el artefacto no se puede leer → ver escenario E.
     - *"contract inputs … do not match"*: se promovió un modelo con otra firma → rollback.
  3. Latencia: el log JSON de la API trae `latency_ms` por petición; `make latency` da una referencia
     (p50 ~32 ms con 2 tickets en la laptop de desarrollo).
- **Mitigación:** si el servicio sigue respondiendo con la versión anterior (`last_refresh_error` en
  `/metadata`), no hay impacto inmediato: corregir la causa y esperar la siguiente consulta. Si el
  problema empezó con una promoción, hacer rollback (D).

### B. Data drift (cambia la distribución de las entradas o del puntaje) · ejecutado en la fase 5
- **Síntomas:** hallazgo SEV3 `drift:<variable>` (PSI ≥ 0,25), `new_category:<variable>` o
  `drift:score`. Todavía no hay etiquetas suficientes para saber si el modelo empeoró.
- **Diagnóstico:**
  1. **¿Es real?** Mirar `n` y la tabla semanal: con menos de 200 filas el PSI no se evalúa, y una
     semana parcial (p. ej., solo fin de semana) puede dar PSI alto sin drift (visto en INC-001).
  2. **¿Es un error de datos o un cambio del mundo?** Una categoría nueva o un salto brusco en un solo
     día suelen ser un error del sistema que envía los datos (campo mal mapeado, unidad cambiada).
     Un aumento gradual, sostenido y con explicación de negocio (más carga, menos personal) es un cambio real.
  3. **¿Llega al puntaje?** Si el PSI del puntaje y el puntaje medio también se mueven, el cambio
     afecta las decisiones (más o menos alertas).
  4. **¿Hay etiquetas de las primeras semanas?** La brecha de calibración semanal es la primera
     métrica en romperse. Si ya empeora, pasar a C sin esperar la cobertura completa.
- **Mitigación:**
  - Error de datos → corregir en el origen; el modelo no se toca.
  - Cambio real → avisar al dueño del modelo y monitorear semanalmente. **SEV3 sostenido dos semanas con
    la calibración en tendencia → reentrenamiento preventivo** (pasos de C).
  - Categoría nueva → el modelo la sirve (`handle_unknown`), pero sin información. Si es frecuente,
    reentrenar cuando haya historia suficiente.

### C. Model drift (empeoran las métricas cuando llegan las etiquetas reales) · ejecutado en la fase 5
- **Síntomas:** hallazgo SEV2 `model:<métrica>` (PR-AUC, Brier, brecha de calibración o costo por
  ticket fuera de la tolerancia del contrato), con ≥ 300 etiquetas y ≥ 50 % de cobertura.
- **Diagnóstico:**
  1. **No mirar una sola métrica.** Si cambió la tasa de incumplimiento, el PR-AUC puede **subir**
     aunque el modelo esté peor (INC-001: 0,435 → 0,572). Brier, calibración y costo son más fiables.
  2. **¿Empezó con una promoción?** `make models` muestra los eventos. Si coincide con un cambio de
     versión → rollback (D) primero, investigar después.
  3. **¿El rollback ayudaría?** Evaluar la versión anterior con las mismas etiquetas recientes. En
     INC-001 la v1 estaba igual de mal (Brier 0,160 vs. 0,164): el problema era el mundo, no la versión.
  4. **¿Qué cambió?** Cruzar con B: la variable con más PSI suele explicar el cambio. La tabla semanal
     muestra desde cuándo.
- **Mitigación (si el rollback no ayuda): reentrenar con el mundo nuevo**
  ```bash
  make data ARGS="<mundo>"                                    # snapshot con etiquetas recientes (demo: simulador)
  make train ARGS="--validation-days 14 --test-days 14"       # validación y prueba DESPUÉS del cambio
  make promote VERSION=<n> REASON="<incidente y evidencia>"   # la puerta compara en la misma ventana
  ```
  Lo decisivo es que validación y prueba caigan **después** del cambio, para que el umbral y la
  evaluación reflejen el mundo nuevo. Si la historia vieja estorba, `--train-days <n>` la recorta (en
  INC-001 no hizo falta). Ventanas más cortas dan métricas más ruidosas: no bajar de ~1.000 tickets por ventana.
- **Verificación:** con tráfico posterior a la promoción y sus etiquetas, `make monitor` sin hallazgos
  SEV2. El reporte compara contra el contrato y el perfil **de la nueva versión**.
- **Ojo:** "dentro del contrato" no significa "el negocio está bien". Si el nuevo contrato promete
  un costo más alto o muchas más alertas, escalar al negocio (costos FP/FN, capacidad de atención).

### D. Rollback (ejecutado en la fase 3)
- **Cuándo:** el problema empezó tras una promoción y no hay una causa evidente en datos o
  infraestructura. Primero se restaura y después se investiga.
- **Comando:**
  ```bash
  make rollback REASON="<qué se observó y desde cuándo>"
  ```
  Devuelve `champion` a la versión anterior en segundos. No pasa por la puerta: esa versión ya fue aprobada.
- **Verificación posterior:** `make models` debe mostrar el alias `champion` en la versión esperada y
  el evento `rolled_back` con tu usuario y motivo.
- **Si responde "no previous champion":** la versión actual es la primera que se promovió o ya se
  revirtió una vez. Opciones: promover explícitamente otra versión aprobada con `make promote
  VERSION=<n>` (pasará por la puerta) o escalar.
- **Después:** post-mortem y, si aplica, corregir el candidato y volver a pasar por la puerta.

### E. Almacenamiento de artefactos sin espacio (visto en la fase 4)
- **Síntomas:** `make train` falla con errores 500 de MLflow al subir artefactos; el log de
  `mlplatform-seaweedfs` dice *"No writable volumes and no free volumes left"*.
- **Diagnóstico:** `df -h /` en el host (en el incidente: 100 % usado, 948 MB libres) y `docker system df`.
- **Mitigación:** liberar espacio (imágenes y volúmenes de Docker sin uso, cachés). SeaweedFS vuelve a
  aceptar escrituras sin reiniciarse. Revisar si quedaron restos de la ejecución fallida (runs y
  modelos `sla_test_*` en MLflow, esquemas `gov_*` en Postgres).
- **Impacto en producción:** el serving **no** se ve afectado mientras no deba cargar una versión nueva.
  El modelo ya cargado vive en memoria.

## Plantilla de post-mortem

- Resumen
- Línea de tiempo
- Impacto
- Causa raíz
- Qué funcionó y qué no
- Acciones (responsable, fecha)
