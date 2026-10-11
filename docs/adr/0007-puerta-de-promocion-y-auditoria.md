# ADR 0007: Puerta de promoción con evaluación común, rollback sin puerta y auditoría en PostgreSQL

- **Estado:** Aceptada
- **Fecha:** 2026-10-11
- **Fase:** 3

## Contexto

Pasar un modelo a producción debe ser una decisión verificable y reversible, y debe quedar registro
de quién la tomó y por qué. Las métricas que cada versión reportó al entrenarse **no son
comparables**: cada una se midió en un periodo distinto.

## Decisión

1. **Contrato obligatorio** (`mlplatform.lifecycle.contract`) en dos niveles:
   - estructura validada con pydantic;
   - reglas de política: commit conocido y sin cambios pendientes, chequeos de datos aprobados,
     métrica principal presente y model card con todas sus secciones.
2. **Evaluación común en el momento de promover.** Candidato, champion y baseline se puntúan con los
   datos actuales sobre la ventana de prueba del candidato. Cada modelo decide con su propio umbral,
   pero todos se juzgan con los mismos costos. La ventana debe ser posterior a todo lo que ambos
   modelos usaron para entrenarse o fijar su umbral.
3. **Criterios de la puerta:**
   - el candidato supera al baseline;
   - no es peor que el champion en la métrica principal (`min_improvement = 0`);
   - no empeora más allá de la tolerancia en calibración (Brier, +0,005) ni en costo por ticket (+0,01).
4. **Rollback sin puerta, pero con motivo obligatorio.** Devuelve `champion` a la versión que lo era
   antes de la promoción vigente. En un incidente la prioridad es restaurar rápido una versión ya aprobada.
5. **Bitácora de auditoría append-only** en `governance.model_events` (PostgreSQL). Registra
   promociones, rechazos y rollbacks con actor, motivo y la evaluación completa.
6. **Separación mecanismo/política:**
   - `mlplatform.lifecycle` decide y no importa MLflow ni bases de datos (lo verifica una prueba de
     arquitectura);
   - `mlplatform.registry` ejecuta las decisiones.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Comparar las métricas que cada versión reportó al entrenarse | Periodos distintos: compara "exámenes" diferentes |
| Exigir mejora estricta (`min_improvement > 0`) | Evita cambios por ruido, pero puede bloquear reentrenamientos con datos frescos; queda configurable |
| Promoción manual sin puerta (alguien mueve el alias) | Sin evidencia ni consistencia; depende de la memoria de quien lo hace |
| Rollback que también pasa por la puerta | Lento en un incidente, y la versión destino ya fue aprobada antes |
| Auditoría solo en tags de MLflow | Se pierde al cambiar de herramienta, no es append-only y no se consulta bien con SQL |
| Opción `--force` para saltarse la puerta | No se implementó: una excepción así requiere un flujo de aprobación humano (fuera de alcance) |

## Consecuencias

- Positivas:
  - Cada cambio de producción tiene evidencia reproducible y queda registrado.
  - La política se prueba en milisegundos con dobles en memoria.
  - Cambiar de registry (por ejemplo, a SageMaker) no toca la política.
- Negativas:
  - La evaluación común exige que los datos de la ventana sigan disponibles al promover.
  - Con `min_improvement = 0` puede haber recambios por diferencias mínimas (se vio en la demostración: +0,0009).
- Reconsiderar si: hay varios aprobadores humanos (flujo de aprobación con firmas), o se adopta
  despliegue gradual (canary o shadow) antes del cambio total de alias.
