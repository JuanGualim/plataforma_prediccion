# Runbook de incidentes

> **Estado:** esqueleto (fase 1). Se completa en la fase 5 con los comandos reales y con un
> incidente simulado documentado de principio a fin.

## Severidades

| Nivel | Criterio | Tiempo de respuesta objetivo |
|---|---|---|
| SEV1 | El servicio de predicción no responde o devuelve errores masivos | _Por definir_ |
| SEV2 | El servicio responde, pero la calidad del modelo está degradada (drift confirmado) | _Por definir_ |
| SEV3 | Señal temprana de drift sin impacto confirmado | _Por definir_ |

## Primeros pasos (cualquier incidente)

1. ¿Qué versión está sirviendo? → `/metadata`
2. ¿Cambió algo recientemente? → historial de promociones
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

### D. Rollback
- Comando: `make rollback` _(fase 3)_
- Verificación posterior: _por definir_

## Plantilla de post-mortem

- Resumen
- Línea de tiempo
- Impacto
- Causa raíz
- Qué funcionó y qué no
- Acciones (responsable, fecha)
