# Fase 2: entrenamiento y evaluación del modelo de riesgo de SLA

> **Estado:** Ejecutado el 2026-10-10 con `make data && make train` (semilla 42).
> Commit `f3f4de2` (sin cambios pendientes) · Python 3.12.15 · scikit-learn 1.9.1 · pandas 3.0.6.
> Artefactos: `data/runs/sla_risk/<timestamp>/model.joblib` y `report.json` (no versionados; se regeneran).
> **Datos sintéticos:** los números muestran que el proceso funciona; no son una promesa de
> desempeño en una empresa real.

## 1. Protocolo de evaluación

| Conjunto | Tickets creados | Se usa "como si hoy fuera" | Filas | Excluidas (resultado aún desconocido) | Prevalencia |
|---|---|---|---|---|---|
| Entrenamiento | 2025-01-06 → 2025-05-05 | 2025-05-06 | 12.310 | 93 | 14,9 % |
| Validación | 2025-05-06 → 2025-06-04 | 2025-06-05 | 3.107 | 105 | 14,5 % |
| Prueba | 2025-06-05 → 2025-07-04 | snapshot | 3.083 | 94 | 15,0 % |

- **Entrenamiento:** ajustar los modelos.
- **Validación:** elegir el modelo y el umbral.
- **Prueba:** medir **una sola vez**, con todo ya decidido.

Ver [ADR 0005](../adr/0005-protocolo-de-evaluacion-y-umbral.md).

## 2. Candidatos (en validación)

| Candidato | PR-AUC ↑ | ROC-AUC ↑ | Brier ↓ | Log loss ↓ | Entrenamiento |
|---|---|---|---|---|---|
| **logreg** ✅ | **0,477** | **0,787** | **0,100** | **0,338** | 0,16 s |
| logreg_balanced | 0,477 | 0,786 | 0,189 | 0,561 | 0,14 s |
| hgb_lr0.05_leaves15 | 0,449 | 0,780 | 0,103 | 0,343 | 1,1 s |
| hgb_lr0.05_leaves31 | 0,436 | 0,774 | 0,104 | 0,347 | 1,8 s |
| hgb_lr0.1_leaves15 | 0,435 | 0,774 | 0,104 | 0,347 | 1,1 s |
| hgb_lr0.1_leaves31 | 0,422 | 0,763 | 0,106 | 0,356 | 1,7 s |
| *baseline priority_x_tier* | *0,307* | *0,714* | *0,111* | *0,371* | — |

**Lecturas:**

- **El modelo simple ganó.** El simulador genera tiempos de resolución *multiplicando* factores,
  así que en escala logarítmica la relación es casi lineal: justo lo que modela una regresión
  logística. El boosting busca interacciones complejas que aquí no existen y, con más hojas, se
  sobreajusta más (la métrica empeora de forma monótona). **En datos reales esta conclusión podría
  invertirse**; por eso se compara siempre, en lugar de asumir que "el modelo más potente gana".
- **`logreg_balanced` ordena igual (mismo PR-AUC), pero sus probabilidades están infladas** (Brier
  casi el doble). Dar más peso a la clase rara no mejora la detección; solo descalibra. El
  desbalance se maneja con el umbral.
- **Regla de selección:** el más simple a menos de 0,005 de PR-AUC del mejor. Aquí el mejor y el
  más simple coinciden.

## 3. Umbral

**Supuesto de negocio:** no detectar un incumplimiento cuesta 5 veces más que escalar un ticket
que no lo necesitaba (`cost_fn = 5`, `cost_fp = 1`, configurable con `--cost-fn` / `--cost-fp`).

| | Valor |
|---|---|
| Umbral elegido en validación (mínimo costo) | **0,16** |
| Óptimo teórico si las probabilidades están calibradas: 1 / (1 + 5) | 0,167 |

Que ambos coincidan confirma que las probabilidades del modelo son confiables (ver calibración abajo).

## 4. Resultado en prueba (evaluado una sola vez)

| | Modelo (logreg) | Baseline priority_x_tier |
|---|---|---|
| PR-AUC | **0,432** | 0,292 |
| ROC-AUC | **0,774** | 0,697 |
| Brier | **0,106** | 0,117 |
| Umbral (elegido en validación) | 0,16 | 0,19 |
| Precisión (de las alertas, cuántas eran incumplimientos reales) | **29,9 %** | 25,5 % |
| Recall (de los incumplimientos, cuántos se detectaron) | **69,5 %** | 63,9 % |
| Tickets alertados | 34,8 % (~36 por día) | 37,6 % |
| **Costo esperado por ticket** | **0,472** | 0,551 |

| Política alternativa | Costo por ticket |
|---|---|
| Nunca alertar | 0,749 |
| Alertar todo | 0,850 |

**Lecturas:**

- El modelo supera al baseline en todas las métricas. Frente a "no hacer nada", **reduce el costo
  esperado un 37 %**; frente a la regla de experto, un 14 %.
- **Validación 0,477 → prueba 0,432.** Una caída es esperable. El ganador se eligió *porque* le fue
  bien en validación (optimismo de la selección), y la prueba es otro periodo. Para eso existe un
  conjunto de prueba intocable.
- **~36 alertas por día:** antes de desplegar, hay que confirmar con el área que puede atender ese
  volumen. Si no puede, el umbral debe fijarse por capacidad y no por costo.

## 5. Calibración en prueba

| Decil | Probabilidad promedio predicha | Tasa real de incumplimiento |
|---|---|---|
| 1 | 2,3 % | 3,9 % |
| 3 | 5,3 % | 6,5 % |
| 5 | 9,4 % | 7,8 % |
| 7 | 15,8 % | 15,3 % |
| 9 | 29,3 % | 31,8 % |
| 10 | 50,7 % | 49,8 % |

Cuando el modelo dice "50 %", ocurre ~50 % de las veces: la probabilidad se puede mostrar a un supervisor.

## 6. Importancia de las variables (permutación, en validación)

Cuánto cae el PR-AUC si se desordena cada columna:

| Columna | Caída de PR-AUC |
|---|---|
| customer_tier | 0,167 |
| priority | 0,119 |
| created_at (hora y día) | 0,099 |
| category | 0,098 |
| channel | 0,045 |
| sla_hours | 0,030 |
| open_tickets_in_queue | 0,012 |
| product | 0,001 |

`product` no aporta nada, y es **correcto**: el simulador no lo usa en ninguna regla. Es una prueba
de cordura de que el modelo aprende la estructura real y no ruido.

## 7. Segmentos en prueba (umbral global 0,16): limitaciones conocidas

| Segmento | n | Incumplimiento real | PR-AUC | Recall | % alertado |
|---|---|---|---|---|---|
| basic | 1.862 | 8,4 % | 0,277 | 41,4 % | 16,3 % |
| business | 939 | 20,7 % | 0,438 | 75,8 % | 53,8 % |
| enterprise | 282 | 39,4 % | 0,605 | 98,2 % | **93,3 %** |
| critical | 211 | 10,9 % | **0,170** | **26,1 %** | 18,0 % |
| high | 608 | 10,7 % | 0,246 | 55,4 % | 27,3 % |
| medium | 1.260 | 15,3 % | 0,493 | 73,6 % | 35,0 % |
| low | 1.004 | 18,0 % | 0,475 | 75,7 % | 42,5 % |

1. **Enterprise queda casi entero en alerta (93 %).** Con un solo umbral, la alerta pierde valor
   para ese segmento. Opciones: umbrales por segmento o costos distintos por nivel de cliente (un
   incumplimiento enterprise probablemente cuesta más). Es una **decisión de negocio**, no técnica.
2. **Los tickets críticos son el punto débil** (detecta 1 de cada 4). Sus incumplimientos dependen
   sobre todo del ruido y de llegar fuera de horario; son pocos (211). Candidatos de mejora:
   interacciones prioridad × fuera de horario, o un análisis dedicado. Debe figurar en la model card (fase 3).
3. Estas tablas son la base del **monitoreo por segmento** de la fase 5: un promedio estable puede
   esconder un segmento que se degrada.

## 8. Qué se guarda

`model.joblib` contiene el **pipeline completo** (preprocesamiento + modelo) y el umbral. El
serving no necesita reimplementar ninguna transformación. `report.json` contiene todo lo anterior,
más la configuración, el rango de datos, el commit de git (y si había cambios sin commitear) y las
versiones de Python y de las librerías. En la fase 3, MLflow reemplazará esta carpeta como registro oficial.
