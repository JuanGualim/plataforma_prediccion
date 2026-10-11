"""Model card del modelo de riesgo de SLA, generada a partir del reporte de entrenamiento.

Las limitaciones por segmento se detectan automáticamente: así la ficha no depende de que
alguien se acuerde de revisarlas.
"""

OWNER = "equipo-analitica-soporte (ficticio)"
MIN_SEGMENT_SIZE = 100
LOW_RECALL = 0.5
HIGH_ALERT_RATE = 0.8


def detect_segment_limitations(segments: dict[str, list[dict]]) -> list[str]:
    findings = []
    for column, rows in segments.items():
        for row in rows:
            if row["n"] < MIN_SEGMENT_SIZE:
                continue
            label = f"`{column}={row['segment']}` (n={row['n']})"
            if row["recall"] < LOW_RECALL:
                findings.append(
                    f"{label}: detecta solo el {row['recall']:.0%} de los incumplimientos."
                )
            if row["alert_rate"] > HIGH_ALERT_RATE:
                findings.append(
                    f"{label}: alerta el {row['alert_rate']:.0%} de los tickets; "
                    "la alerta pierde poder de discriminación."
                )
    return findings


def build_model_card(report: dict, model_name: str) -> str:
    test = report["test"]["model"]
    baseline = report["test"]["baseline_priority_x_tier"]["ranking"]
    threshold = report["threshold"]
    data = report["data"]
    cfg = report["config"]
    limitations = detect_segment_limitations(report["test"]["segments"])
    limitation_lines = "\n".join(f"- {line}" for line in limitations) or "- Ninguna detectada."
    theory = threshold["calibrated_theoretical_optimum"]

    return f"""# Model card: {model_name}

## Propósito
Estimar, en el momento de crear un ticket de soporte, la probabilidad de que no se resuelva
dentro del SLA comprometido, para que un supervisor priorice o escale a tiempo.

## Uso previsto y fuera de alcance
- **Previsto:** ordenar y alertar tickets recién creados para revisión humana.
- **Fuera de alcance:** decisiones automáticas sobre personas (agentes o clientes), evaluación
  de desempeño individual, y tickets ya avanzados (el modelo solo ve información de T0).

## Datos
- Fuente: `support.tickets` (**datos sintéticos** del simulador del proyecto).
- Rango: {data["range"][0]} → {data["range"][1]}.
- Entrenamiento antes de {data["validation_cutoff"]}; validación hasta {data["test_cutoff"]};
  prueba después. Filas: {data["n"]}.
- Entradas: {", ".join(f"`{c}`" for c in report["features"]["input_columns"])}. Ninguna es
  posterior a la creación del ticket (verificado por el catálogo de campos).
- Sin datos personales entre las entradas (el texto libre no se usa).

## Métricas
Modelo seleccionado: **{report["selected"]["name"]}** (de {len(report["candidates_validation"])}
candidatos, elegido por PR-AUC en validación).

| Prueba | Modelo | Baseline prioridad × nivel |
|---|---|---|
| PR-AUC | {test["ranking"]["pr_auc"]:.3f} | {baseline["pr_auc"]:.3f} |
| ROC-AUC | {test["ranking"]["roc_auc"]:.3f} | {baseline["roc_auc"]:.3f} |
| Brier | {test["ranking"]["brier"]:.3f} | {baseline["brier"]:.3f} |

## Umbral de decisión
Alertar si la probabilidad es ≥ **{threshold["value"]:.2f}**. Elegido en validación minimizando el
costo esperado con costo de no detectar = {cfg["cost_false_negative"]} y costo de falsa alarma =
{cfg["cost_false_positive"]} (óptimo teórico calibrado: {theory:.3f}).
En prueba: precisión {test["decision"]["precision"]:.1%}, recall {test["decision"]["recall"]:.1%},
~{test["decision"]["alerts_per_day"]:.0f} alertas por día.

## Limitaciones
- Entrenado con datos sintéticos: no demuestra valor de negocio real.
- Los costos de error son un supuesto que el área debe validar.
- Limitaciones por segmento detectadas automáticamente en prueba:
{limitation_lines}

## Responsable
{OWNER}. Cambios de versión solo a través de la puerta de promoción de la plataforma.
"""
