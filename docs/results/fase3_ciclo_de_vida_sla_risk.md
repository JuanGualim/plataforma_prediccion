# Fase 3: ciclo de vida del modelo de SLA en MLflow (demostración)

> **Estado:** Ejecutado el 2026-10-11 contra el stack local (`make up`): MLflow 3.17.0, PostgreSQL 16 y
> SeaweedFS 4.48. Cada paso es un comando de `make`. Los números vienen de la bitácora
> `governance.model_events`. **Datos sintéticos.**

## Guion: el paso del tiempo

El simulador genera un mundo de 210 días. La opción `--as-of` toma la "foto" en un momento dado: así
se simula que pasa el tiempo **en el mismo mundo**, en lugar de inventar otro.

| # | Comando | Qué representa |
|---|---|---|
| 1 | `make data ARGS="--days 210 --as-of 2025-07-05"` | Hoy es 5 de julio: 18.792 tickets conocidos |
| 2 | `make train` → **v1** | Primer modelo (regresión logística, umbral 0,16) |
| 3 | `make promote VERSION=1` | Primera promoción |
| 4 | `make train ARGS="--candidates hgb_lr0.1_leaves31"` → **v2** | Un equipo propone gradient boosting |
| 5 | `make promote VERSION=2` | ¿Reemplaza al champion? |
| 6 | `make data ARGS="--days 210"` | Pasan 30 días: hoy es 4 de agosto (21.738 tickets) |
| 7 | `make train` → **v3** | Reentrenamiento con los datos nuevos (umbral 0,18) |
| 8 | `make promote` | ¿Reemplaza al champion? |
| 9 | `make rollback REASON="..."` | Simulacro de incidente |

## Resultados de la puerta

### Paso 3: v1 (primera promoción) → ✅ APROBADA

Ventana común: 5 jun → 4 jul (3.093 tickets).

| | PR-AUC | ROC-AUC | Brier | Costo/ticket |
|---|---|---|---|---|
| v1 (candidato) | **0,482** | 0,794 | 0,109 | 0,455 |
| Baseline prioridad × nivel | 0,319 | 0,710 | 0,123 | 0,557 |

Sin champion previo, basta con un contrato válido, una ventana no vista y superar al baseline.

### Paso 5: v2 (gradient boosting) → ❌ RECHAZADA

Misma ventana que v1.

| | PR-AUC | Brier | Costo/ticket |
|---|---|---|---|
| v2 (candidato) | 0,441 | 0,116 | 0,523 |
| v1 (champion) | **0,482** | **0,109** | **0,455** |
| Baseline | 0,319 | 0,123 | 0,557 |

```
REJECTED
  [ok]   contract: complete and valid
  [ok]   unseen_evaluation_window: window starts 2025-06-05, n=3093
  [ok]   beats_baseline: pr_auc 0.4408 vs baseline 0.3191
  [FAIL] vs_champion: pr_auc 0.4408 vs champion 0.4815 (required >= +0.0)
  [FAIL] guardrail_brier: 0.1158 vs champion 0.1091 (tolerance +0.005)
  [FAIL] guardrail_cost_per_ticket: 0.5234 vs champion 0.4552 (tolerance +0.01)
```

Superar al baseline **no basta**: el candidato es peor que lo que ya está en producción. El champion no cambió.

### Paso 8: v3 (reentrenada 30 días después) → ✅ APROBADA, por un margen mínimo

Ventana común nueva: 5 jul → 3 ago (2.900 tickets), que ninguno de los dos modelos había visto.

| | PR-AUC | Brier | Costo/ticket |
|---|---|---|---|
| v3 (candidato) | 0,4636 | 0,1022 | 0,4434 |
| v1 (champion) | 0,4627 | 0,1021 | 0,4428 |
| Baseline | 0,279 | 0,115 | 0,550 |

**Lectura honesta:** v3 y v1 son prácticamente iguales (+0,0009 de PR-AUC; el costo es 0,0006 peor,
dentro de la tolerancia). Es lo esperable: el mundo simulado **no cambió** en esos 30 días, así que
más datos del mismo proceso no enseñan nada nuevo. La política actual (`min_improvement = 0`)
privilegia la frescura y acepta el recambio. Una política con `min_improvement > 0` lo habría
rechazado para evitar cambios por ruido. Es una decisión de gobierno, configurable en `PromotionPolicy`.

### Paso 9: rollback → champion v3 → v1

```
$ make rollback
Falta el motivo: make rollback REASON="..."

$ make rollback REASON="simulacro: quejas de supervisores por alertas tras desplegar v3"
rollback: champion v3 -> v1          (~6 s, casi todo es el arranque de Python)

$ make rollback REASON="otro intento"
ERROR version 1 has no previous champion to return to
```

## Estado final del registry (`make models`)

```
version    alias      status test_pr_auc git_commit
      1 champion    champion      0.4815    04d5788
      2             rejected      0.4408    4ce541e
      3          rolled_back      0.4636    4ce541e
```

## Bitácora de auditoría (consulta SQL directa)

```
 event_id | event_type  | desde | hacia | actor | motivo
----------+-------------+-------+-------+-------+-----------------------------------------------
        1 | promoted    |       | 1     | juang | primer modelo de riesgo de SLA
        2 | rejected    | 1     | 2     | juang | probar boosting con más hojas
        3 | promoted    | 1     | 3     | juang | reentrenamiento con 30 días más de datos
        4 | rolled_back | 3     | 1     | juang | simulacro: quejas de supervisores por alertas
```

## Trazabilidad de v1 (de su `contract.json` en MLflow)

| Campo | Valor |
|---|---|
| Commit | `04d5788` (sin cambios pendientes) |
| Huella del dataset | `43c6fbc85408dfd0…` (sha256 de la tabla de entrenamiento al 5 de julio) |
| Lockfile | `35c3b917171c9333…` |
| Firma | `created_at` datetime con zona horaria; 5 columnas de texto; `sla_hours` y `open_tickets_in_queue` enteras |

Aunque la base de datos ya contiene la foto del 4 de agosto, la huella identifica con exactitud qué
datos usó v1. Regenerarlos es `make data ARGS="--days 210 --as-of 2025-07-05"`.

## Model card de v1: limitaciones detectadas automáticamente

- `customer_tier=basic` (n=1848): detecta solo el 46 % de los incumplimientos.
- `customer_tier=enterprise` (n=320): alerta el 90 % de los tickets; la alerta pierde poder de discriminación.
- `priority=critical` (n=234): detecta solo el 24 % de los incumplimientos.

Son las mismas que se encontraron a mano en la fase 2, más una nueva (*basic*). Ahora quedan escritas
en cada versión sin depender de que alguien las revise.

## Cómo explorarlo

- UI de MLflow: http://localhost:5000. Experimento `sla_risk`: un run padre por entrenamiento, con un
  run hijo por candidato. Modelo registrado `sla_risk` con alias `champion`.
- Artefactos de cada versión: `contract.json`, `model_card.md`, `report.json` y el modelo en formato `skops`.
