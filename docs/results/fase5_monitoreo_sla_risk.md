# Fase 5: monitoreo y simulación de drift del modelo de SLA (demostración)

> **Estado:** Ejecutado el 2026-10-12 contra el stack local (`make up`), con el serving en Docker.
> **Datos sintéticos:** el drift lo provoca el simulador a propósito. Los números prueban que el
> monitoreo detecta y explica el cambio, no que el modelo tenga valor de negocio.
> Post-mortem del incidente: [INC-001](../incidents/INC-001-drift-carga-sla-risk.md).

## 1. Qué se construyó

| Nivel | Pregunta | Fuente | Señal | Severidad |
|---|---|---|---|---|
| Servicio | ¿La API responde rápido y sin errores? | `monitoring.requests` (una fila por llamada a `/predict`, también las fallidas) | tasa de 5xx, p95 | SEV1 (5xx > 1 %), SEV3 (p95 > 200 ms) |
| Datos y puntajes | ¿Lo que llega se parece a lo que el modelo conoció? | `monitoring.predictions` vs. `reference_profile.json` de la versión | PSI por variable y del puntaje; categorías nuevas | SEV3 (PSI ≥ 0,25 o categoría nueva) |
| Modelo | ¿Sigue acertando cuando llega el resultado real? | predicciones unidas con `support.tickets.sla_breached` | PR-AUC, Brier, brecha de calibración y costo vs. el contrato | SEV2 (con ≥ 300 etiquetas y ≥ 50 % de cobertura) |

Piezas:
- `mlplatform.monitoring` (`drift`, `performance`, `service`, `rules`): genérico, sin nada del caso de SLA.
- Cada entrenamiento guarda en MLflow un **perfil de referencia** calculado sobre la ventana de prueba
  (datos que el modelo no usó para aprender ni para elegir el umbral) y las categorías vistas al entrenar.
- `make replay`: el "sistema de tickets" simulado llama a `/predict` al crear cada ticket, **solo con
  los campos T0** y como tráfico `live`.
- `make monitor`: reporte en Markdown y JSON (`data/reports/monitoring/`), con ventanas por **fecha
  del evento** (`created_at`) y no por la hora de la petición. Así, dos meses reproducidos en 12 s se
  analizan como dos meses.

## 2. El escenario

`--days 300 --drift-start 2025-08-15 --drift-capacity 85`: desde el 15 de agosto el equipo de soporte
atiende menos tickets (capacidad 110 → 85, "pérdida de personal"). Esto produce **data drift** (la cola
crece) y **concept drift** (con la misma cola se incumple más). Ver [simulador](../simulator.md#5-escenarios-de-drift-fase-5).

## 3. La demostración, en cinco actos

| Acto | Comando | Resultado |
|---|---|---|
| 1. Antes del drift | `make data ARGS="<mundo> --as-of 2025-08-01"`, `make train`, `make promote VERSION=4` | v4 aprobada: PR-AUC 0,435 (baseline 0,273), Brier 0,098, costo 0,440 por ticket |
| 2. Llega el tráfico | `make replay ARGS="--from 2025-08-01 --to 2025-10-01 <mundo>"` y `make monitor` | 6.148 tickets servidos por la v4 en 11,5 s. **SEV3**: PSI de `open_tickets_in_queue` = 0,80. Sin etiquetas todavía: el modelo no se puede juzgar |
| 3. Llegan las etiquetas | `make data ARGS="<mundo> --as-of 2025-10-15"` y `make monitor` | Cobertura 100 %. **SEV2**: Brier 0,144 (límite 0,118) y costo 0,559 (límite 0,490) |
| 4. Remediación | `make train ARGS="--validation-days 14 --test-days 14"`, `make promote VERSION=5` | v5 aprobada en la ventana común (1–15 oct): costo 0,563 vs. 0,616 de la v4; Brier 0,157 vs. 0,162 |
| 5. Verificación | `make replay` (15 oct – 1 nov) con la v5, etiquetas al 2 nov, `make monitor` | **Ningún hallazgo.** PSI máximo 0,055; las 4 métricas dentro del contrato |

## 4. Lo que vio el monitoreo, semana a semana (v4)

| Semana | n | Cola media | PSI cola | PSI puntaje | Puntaje medio | Tasa real | Brecha de calibración |
|---|---|---|---|---|---|---|---|
| 28 jul* | 203 | 79,9 | 3,64 | 0,05 | 0,150 | 0,153 | −0,003 |
| 4 ago | 719 | 112,0 | 0,16 | 0,05 | 0,164 | 0,185 | −0,021 |
| 11 ago | 702 | 99,0 | 0,18 | 0,01 | 0,142 | 0,152 | −0,011 |
| **18 ago** | 716 | 112,4 | **0,26** | 0,01 | 0,157 | 0,193 | −0,036 |
| 25 ago | 718 | 115,1 | 0,24 | 0,04 | 0,168 | 0,206 | −0,038 |
| **1 sep** | 710 | 150,0 | **3,01** | 0,21 | 0,214 | 0,300 | **−0,086** |
| 8 sep | 667 | 159,0 | 3,23 | 0,38 | 0,210 | 0,279 | −0,069 |
| 15 sep | 722 | 146,0 | 2,78 | 0,16 | 0,206 | 0,277 | −0,071 |
| 22 sep | 725 | 155,3 | 3,32 | 0,31 | 0,216 | 0,287 | −0,071 |

\* Semana parcial (viernes a domingo): la cola del fin de semana es menor y el PSI se dispara. **Es un
falso positivo** del corte semanal, no un drift. El resto de variables (canal, prioridad, categoría,
producto, hora) se mantuvo con PSI < 0,02 todo el periodo.

**Lectura:**
1. **La señal temprana llegó primero.** La cola cruzó el umbral de alerta (0,25) en la primera semana
   completa después del cambio (18 de agosto), cuando todavía no había etiquetas. La calibración
   superó su límite dos semanas después (1 de septiembre), y eso solo se puede confirmar cuando
   vencen los plazos de esos tickets.
2. **El modelo subestima el riesgo.** Desde septiembre, el puntaje medio quedó ~7 puntos por debajo
   de la tasa real: el modelo "ve" la cola más larga y sube el puntaje, pero no lo suficiente, porque
   aprendió con un equipo que tenía más capacidad. Eso es el concept drift.
3. **El PR-AUC habría ocultado el incidente.** Subió de 0,435 (contrato) a 0,572 mientras el modelo
   empeoraba. El PR-AUC depende de la prevalencia: si los incumplimientos pasan de 15 % a 23 %, sube
   aunque el modelo no mejore. Lo que detectó el problema fueron el **Brier**, la **calibración** y el
   **costo**. Por eso la regla de monitoreo no usa una sola métrica.

## 5. ¿Rollback o reentrenamiento?

El runbook dice que, si el problema empezó con una promoción, primero se revierte. Aquí no: el
problema empezó con un cambio en el mundo. Se verificó con datos antes de decidir:

| Versión (septiembre, n = 3.090) | PR-AUC | Brier | Brecha | Recall | Costo por ticket |
|---|---|---|---|---|---|
| v1 (champion anterior) | 0,620 | 0,160 | −0,054 | 0,791 | 0,584 |
| v4 (champion) | 0,621 | 0,164 | −0,073 | 0,752 | 0,593 |

Revertir a la v1 no arreglaba nada: las dos aprendieron el mundo de antes. La salida fue reentrenar.

Para reentrenar se probó si convenía **descartar la historia vieja** (`--train-days`, opción nueva):

| Historia de entrenamiento | PR-AUC prueba | Brier prueba | Costo prueba |
|---|---|---|---|
| Toda (26.143 filas) | 0,590 | 0,157 | 0,563 |
| 90 días | 0,591 | 0,155 | 0,589 |
| 60 días | 0,589 | 0,155 | 0,570 |
| 35 días | 0,590 | 0,156 | 0,561 |

No cambió nada relevante. Lo decisivo fue que **validación y prueba cayeran después del drift**
(ventanas de 14 días): el umbral y la evaluación se hacen sobre el mundo nuevo. Se dejó la historia
completa, que es la opción más simple. La opción `--train-days` queda disponible y probada.

## 6. Después de la remediación (v5, tráfico del 15 oct al 1 nov)

| Métrica | Contrato v5 | Observado | Límite |
|---|---|---|---|
| PR-AUC | 0,590 | 0,604 | ≥ 0,540 |
| Brier | 0,157 | 0,170 | ≤ 0,177 |
| Brecha de calibración | 0 | −0,042 | ±0,05 |
| Costo por ticket | 0,563 | 0,567 | ≤ 0,613 |

**Advertencias honestas:**
- **"Dentro del contrato" no significa "el negocio está bien".** El costo por ticket de la v5 (0,57)
  es más alto que el de la v4 antes del drift (0,44), porque ahora se incumple el doble. El modelo
  describe bien el mundo nuevo, pero no puede devolverle capacidad al equipo.
- **La v5 alerta en el 61 % de los tickets** (recall 0,86). Con costos 1:5 es lo óptimo, pero un equipo
  que ya perdió personal quizá no pueda atender tantas alertas. Revisar los costos es una decisión del
  negocio, no del modelo.
- El Brier (0,170) y la brecha (−0,042) están cerca del límite y la cola sigue alta: la v5 queda **en
  observación** (ver acciones en el post-mortem).

## 7. Servicio durante la demostración

| Ventana | Peticiones (lotes de 50) | 5xx | p50 | p95 | p99 |
|---|---|---|---|---|---|
| Reproducción de ago–sep (v4) | 123 | 0 | 43 ms | 59 ms | 120 ms |
| Reproducción de oct (v5) | 160 | 0 | 42 ms | 60 ms | 160 ms |

La latencia es la de la fase 4 (~0,9 ms por ticket en lotes de 50). El cambio de champion de la v4 a
la v5 se aplicó sin reiniciar el servicio.

## 8. Problemas encontrados durante la implementación

| Síntoma | Causa | Solución |
|---|---|---|
| El disco llegó otra vez al 100 % | Cada reconstrucción de la imagen de serving dejaba una capa nueva de ~500 MB con las dependencias, y las imágenes viejas quedaban huérfanas | Dependencias y código en capas separadas: un cambio de código ya no reinstala nada. Se borraron solo imágenes huérfanas del propio proyecto |
| Semana parcial con PSI 3,6 sin drift | Ventana de viernes a domingo comparada con una referencia de semanas completas | Documentado como limitación. Se lee junto con `n` y la semana completa siguiente |
