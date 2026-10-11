# Runbook de incidentes

> **Estado:** parcial. Rollback (D) ejecutado en la fase 3; caída del servicio (A) y almacenamiento
> lleno (E) con comandos reales de la fase 4. Drift (B, C) se completa en la fase 5.

## Severidades

| Nivel | Criterio | Tiempo de respuesta objetivo |
|---|---|---|
| SEV1 | El servicio de predicción no responde o devuelve errores masivos | _Por definir_ |
| SEV2 | El servicio responde, pero la calidad del modelo está degradada (drift confirmado) | _Por definir_ |
| SEV3 | Señal temprana de drift sin impacto confirmado | _Por definir_ |

## Primeros pasos (cualquier incidente)

1. ¿Qué versión está sirviendo? → `curl localhost:8000/metadata` y `make models` (alias `champion`)
2. ¿Cambió algo recientemente? → `make models` muestra los últimos eventos de `governance.model_events`
3. ¿Es un problema del servicio, de los datos o del modelo? → paneles de monitoreo

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

### B. Data drift (cambia la distribución de las entradas)
- Síntomas: _por definir_
- Diagnóstico: _por definir_
- Mitigación: _por definir_

### C. Model drift (empeoran las métricas cuando llegan las etiquetas reales)
- Síntomas: _por definir_
- Diagnóstico: _por definir_
- Mitigación: _por definir_

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
