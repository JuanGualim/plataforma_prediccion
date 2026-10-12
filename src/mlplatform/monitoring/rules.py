"""Reglas de alerta: convierten mediciones en hallazgos con severidad y escenario del runbook.

Severidades (docs/incident_runbook.md):
- SEV1: el servicio no responde o falla masivamente.
- SEV2: la calidad del modelo está degradada (confirmado con etiquetas reales).
- SEV3: señal temprana (drift de datos o de puntajes) sin impacto confirmado todavía.
"""

from dataclasses import dataclass

from mlplatform.monitoring.drift import DriftReport
from mlplatform.monitoring.performance import MIN_LABELS, PerformanceCheck


@dataclass(frozen=True)
class AlertThresholds:
    p95_ms: float = 200.0
    server_error_rate: float = 0.01
    min_label_coverage_for_model_checks: float = 0.5


@dataclass(frozen=True)
class Finding:
    level: str  # service | data | prediction | model
    severity: str  # SEV1 | SEV2 | SEV3
    check: str
    detail: str
    runbook: str  # escenario del runbook


def evaluate_rules(
    service: dict[str, float] | None,
    drift: DriftReport | None,
    performance: list[PerformanceCheck] | None,
    n_labels: int,
    label_coverage: float,
    thresholds: AlertThresholds | None = None,
) -> list[Finding]:
    t = thresholds or AlertThresholds()
    findings: list[Finding] = []

    if service and service.get("requests", 0):
        if service["server_error_rate"] > t.server_error_rate:
            findings.append(
                Finding(
                    "service",
                    "SEV1",
                    "server_error_rate",
                    f"{service['server_error_rate']:.1%} de respuestas 5xx",
                    "A",
                )
            )
        if service["p95_ms"] > t.p95_ms:
            findings.append(
                Finding(
                    "service",
                    "SEV3",
                    "latency_p95",
                    f"p95 {service['p95_ms']:.0f} ms > {t.p95_ms:.0f} ms",
                    "A",
                )
            )

    if drift is not None:
        for f in drift.features:
            if f.new_categories:
                findings.append(
                    Finding(
                        "data",
                        "SEV3",
                        f"new_category:{f.name}",
                        f"valores nunca vistos: {f.new_categories}",
                        "B",
                    )
                )
            elif f.status == "alert":
                findings.append(
                    Finding("data", "SEV3", f"drift:{f.name}", f"PSI {f.psi:.2f} (n={f.n})", "B")
                )
        if drift.score.status == "alert":
            findings.append(
                Finding(
                    "prediction",
                    "SEV3",
                    "drift:score",
                    f"PSI del puntaje {drift.score.psi:.2f}",
                    "B",
                )
            )

    enough_labels = (
        n_labels >= MIN_LABELS and label_coverage >= t.min_label_coverage_for_model_checks
    )
    if performance and enough_labels:
        for check in performance:
            if not check.passed:
                findings.append(
                    Finding(
                        "model",
                        "SEV2",
                        f"model:{check.name}",
                        f"observado {check.observed:.3f}, esperado "
                        f"{check.expected:.3f} (límite {check.limit})",
                        "C",
                    )
                )
    return findings
