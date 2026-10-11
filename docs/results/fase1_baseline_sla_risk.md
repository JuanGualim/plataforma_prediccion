# Fase 1: baselines del modelo de riesgo de SLA

> **Nota (fase 2):** este registro usó una partición en dos conjuntos (entrenamiento/prueba). Desde la
> fase 2, `make baseline` usa entrenamiento/validación/prueba, y la cifra vigente del baseline
> `priority_x_tier` en prueba es PR-AUC 0,292 (ver [fase 2](fase2_entrenamiento_sla_risk.md)).

> **Estado:** Ejecutado el 2026-10-10 con `make data && make baseline` (semilla 42, configuración
> por defecto del simulador). Reporte completo: `data/reports/sla_risk_baseline.json` (no versionado; se regenera).
> **Datos sintéticos:** estos números muestran que el flujo funciona y fijan la vara para la
> fase 2; no representan el desempeño esperado en una empresa real.

## Partición temporal

| | Valor |
|---|---|
| Periodo de datos | 2025-01-06 a 2025-07-04 |
| Fecha de corte | 2025-06-04 (30 días antes del ticket más reciente) |
| Entrenamiento | 15.360 tickets creados antes del corte, con resultado conocido en el corte |
| Excluidos del entrenamiento | 112 tickets previos al corte cuyo resultado aún no se conocía en esa fecha |
| Prueba | 3.226 tickets creados desde el corte, con resultado conocido en el snapshot |
| Excluidos de la prueba | 94 tickets sin resultado conocido todavía |
| Prevalencia (prueba) | 15,0 % de incumplimiento |

## Resultados en el conjunto de prueba

| Baseline | PR-AUC ↑ | ROC-AUC ↑ | Brier ↓ | Log loss ↓ |
|---|---|---|---|---|
| `prior`: siempre la tasa histórica | 0,150 | 0,500 | 0,128 | 0,423 |
| `priority_x_tier`: tasa histórica por prioridad × nivel | **0,290** | **0,701** | **0,117** | **0,385** |
| ⚠️ `LEAKY_with_reassignment_count` (contrafactual, inválido) | 0,403 | 0,785 | 0,108 | 0,352 |

## Lectura

- **`prior` se comporta exactamente como predice la teoría:** PR-AUC = prevalencia y ROC-AUC = 0,5.
  Es la referencia "sin información".
- **`priority_x_tier` casi duplica el PR-AUC** con una regla que cualquier supervisor podría
  escribir. **Es la vara que el modelo de la fase 2 debe superar.** Si un modelo de ML no le gana
  claramente a esta regla, su complejidad no se justifica.
- **El contrafactual con fuga** agrega `reassignment_count`, un dato que solo se conoce después de
  crear el ticket. Mejora todas las métricas, y justo por eso es peligroso: en producción ese dato
  no existe al momento de predecir. Este número muestra lo que el catálogo de campos
  ([ADR 0004](../adr/0004-catalogo-de-campos-contra-fugas.md)) impide.

## Métrica principal para la fase 2

**PR-AUC**, porque la clase positiva (incumplir) es minoritaria (~15 %) y lo que importa es
encontrar esos casos con pocas falsas alarmas. ROC-AUC se reporta como referencia, y Brier y
log loss como métricas de calidad de la probabilidad (importan si el score se muestra a un supervisor).
