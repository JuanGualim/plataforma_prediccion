# INC-001: el modelo de SLA subestima el riesgo tras la pérdida de capacidad del equipo

> **Incidente simulado** (fase 5). El cambio lo provocó el simulador a propósito para ejercitar el
> monitoreo y el runbook. Los comandos y los números son reales; el impacto de negocio, no.
> Detalle técnico y tablas completas: [resultados de la fase 5](../results/fase5_monitoreo_sla_risk.md).

| Campo | Valor |
|---|---|
| Severidad máxima | SEV2 (calidad del modelo degradada, confirmada con etiquetas reales) |
| Modelo | `sla_risk` v4 (champion desde el 2025-08-01) |
| Escenarios del runbook | B (data drift) → C (model drift) |
| Estado | Mitigado con la v5; v5 en observación |

## Resumen

Desde el 15 de agosto de 2025, el equipo de soporte atiende menos tickets por hora. Las colas
crecieron y los incumplimientos del SLA pasaron de ~15 % a ~29 %. El modelo v4, entrenado con el
equipo anterior, siguió ordenando bien los tickets, pero **subestimaba la probabilidad de incumplir**
en unos 7 puntos. Con el umbral fijo, dejó de alertar en tickets que sí se incumplían. Se reentrenó
con validación y prueba posteriores al cambio (v5). La v5 pasó la puerta y se verificó con tráfico nuevo.

## Línea de tiempo (fechas del mundo simulado)

| Fecha | Evento |
|---|---|
| 2025-08-01 | v4 promovida (aprobada por la puerta: PR-AUC 0,435, Brier 0,098) |
| 2025-08-15 | **Inicio:** la capacidad del equipo cae de 110 a 85 |
| Semana del 18 ago | El PSI de `open_tickets_in_queue` llega a 0,26: **SEV3** (señal temprana, escenario B) |
| Semana del 1 sep | El PSI de la cola llega a 3,0 y el del puntaje a 0,21. La brecha de calibración llega a −0,086 (se confirma cuando vencen los plazos de esos tickets) |
| 2025-10-01 | Corte del análisis de los dos meses: **SEV3** por la cola (PSI 0,80); sin etiquetas aún |
| 2025-10-15 | Con 100 % de etiquetas: **SEV2**. Brier 0,144 (límite 0,118) y costo 0,559 por ticket (límite 0,490) |
| 2025-10-15 | Diagnóstico: el rollback a la v1 no mejora (Brier 0,160, costo 0,584 en septiembre) |
| 2025-10-15 | v5 entrenada con validación y prueba de 14 días, ambas posteriores al cambio. **Aprobada** |
| 2025-11-02 | Verificación: 1.822 tickets nuevos servidos por la v5, 98 % con etiqueta, **sin hallazgos** |

## Impacto

- **Servicio:** ninguno. 0 errores 5xx, p95 de ~60 ms en todo el periodo; el cambio de la v4 a la v5
  se aplicó sin reiniciar.
- **Modelo:** en septiembre la v4 detectó el 75 % de los incumplimientos (recall 0,752). Su promesa de
  calibración ya no se cumplía, y el costo esperado por ticket subió 27 % frente al contrato (0,559 vs. 0,440).
- **Negocio (simulado):** sin el monitoreo de calibración, el problema se habría visto solo como
  "hay más incumplimientos", sin saber que el modelo también estaba fallando.

## Causa raíz

Un **cambio en el mundo**, no en el software: menos capacidad del equipo. Produjo dos tipos de drift
a la vez:
1. **Data drift:** colas más largas (media de 105 a ~150). El modelo nunca había visto colas así de
   frecuentes.
2. **Concept drift:** con la misma cola, ahora se incumple más. La relación "cola → riesgo" que
   aprendió el modelo dejó de ser verdad. Por eso el modelo sube el puntaje con la cola, pero no lo suficiente.

Ningún control de la plataforma podía evitarlo: lo que falló es el supuesto de que el futuro se
parece al pasado. Lo que sí se podía controlar era **cuánto tardábamos en verlo y si sabíamos qué hacer**.

## Qué funcionó

- **La señal temprana:** el drift de datos alertó semanas antes de tener etiquetas para confirmar el daño.
- **La regla de no confiar en una sola métrica:** el PR-AUC **subió** (0,435 → 0,572) porque aumentó
  la prevalencia. Un monitoreo basado solo en PR-AUC habría dicho "todo mejoró".
- **El perfil de referencia por versión:** cada versión trae su propia "normalidad". La v5 se
  monitoreó contra el mundo nuevo, no contra el de la v4.
- **La disciplina del runbook:** antes de revertir, se comprobó con datos que el rollback no ayudaba.
- **La puerta de promoción:** comparó la v5 con la v4 en la misma ventana posterior al cambio, sin
  reglas especiales para el incidente.

## Qué no funcionó o falta

- **El monitoreo se corre a mano** (`make monitor`). En producción, una corrida semanal programada
  habría levantado el SEV3 la semana del 18 de agosto. Aquí el análisis se reconstruyó después.
- **Semanas parciales generan falsos positivos** (PSI 3,6 en un viernes a domingo sin drift).
- **La alarma SEV2 depende de etiquetas que tardan días.** Entre la señal temprana y la confirmación
  pasaron ~3 semanas. Durante ese tiempo no hubo una acción intermedia definida.
- **No existe un umbral de capacidad de alertas.** La v5 alerta en el 61 % de los tickets.

## Acciones

| # | Acción | Tipo | Responsable | Estado |
|---|---|---|---|---|
| 1 | Programar `make monitor` semanal y enviar los hallazgos a un canal | Detección | Plataforma | Pendiente (fase 10: CronJob en kind) |
| 2 | Marcar las semanas incompletas en la tabla semanal y no alertar con ellas | Detección | Plataforma | Pendiente |
| 3 | SEV3 sostenido 2 semanas con calibración en tendencia → reentrenamiento preventivo (runbook B) | Proceso | Dueño del modelo | Hecho (runbook) |
| 4 | Revisar los costos FP/FN con el negocio dada la nueva tasa de alertas (61 %) | Negocio | Dueño del modelo + soporte | Pendiente |
| 5 | Mantener la v5 en observación: Brier 0,170 y brecha −0,042, cerca de sus límites | Seguimiento | Dueño del modelo | Abierto |
| 6 | Opción `--train-days` para entrenar solo con historia reciente | Remediación | Plataforma | Hecho (no hizo falta en este incidente) |
