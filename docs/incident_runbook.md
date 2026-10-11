# Runbook de incidentes

> **Estado:** parcial. El rollback (sección D) se ejecutó en la fase 3. El resto se completa en la fase 5
> con el monitoreo y un incidente simulado de principio a fin.

## Severidades

| Nivel | Criterio | Tiempo de respuesta objetivo |
|---|---|---|
| SEV1 | El servicio de predicción no responde o devuelve errores masivos | _Por definir_ |
| SEV2 | El servicio responde, pero la calidad del modelo está degradada (drift confirmado) | _Por definir_ |
| SEV3 | Señal temprana de drift sin impacto confirmado | _Por definir_ |

## Primeros pasos (cualquier incidente)

1. ¿Qué versión está sirviendo? → `make models` (alias `champion`); en la fase 4, también `/metadata`
2. ¿Cambió algo recientemente? → `make models` muestra los últimos eventos de `governance.model_events`
3. ¿Es un problema del servicio, de los datos o del modelo? → paneles de monitoreo

## Escenarios

### A. Caída o latencia alta del servicio
- Síntomas: _por definir_
- Diagnóstico: _por definir_
- Mitigación: _por definir_

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

## Plantilla de post-mortem

- Resumen
- Línea de tiempo
- Impacto
- Causa raíz
- Qué funcionó y qué no
- Acciones (responsable, fecha)
