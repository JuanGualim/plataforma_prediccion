"""Puerta de promoción: ¿puede un candidato reemplazar al champion?

Principio: candidato, champion y baseline se comparan sobre la MISMA ventana de evaluación,
calculada en el momento de la promoción. Comparar el número que cada modelo reportó al
entrenarse no sirve: cada uno se midió en un periodo distinto.

La ventana debe ser posterior a todo lo que ambos modelos usaron para entrenarse o elegir
su umbral; si no, uno de los dos estaría "rindiendo un examen que ya vio".
"""

from dataclasses import dataclass, field

import pandas as pd

from mlplatform.lifecycle.contract import DeploymentContract, contract_violations


@dataclass(frozen=True)
class PromotionPolicy:
    primary_metric: str = "pr_auc"  # mayor es mejor
    # El candidato debe ser al menos tan bueno como el champion (+ este margen).
    min_improvement: float = 0.0
    # Y debe superar al baseline por al menos este margen.
    min_gain_over_baseline: float = 0.0
    # Métricas "menor es mejor" que no pueden empeorar más que la tolerancia.
    guardrails: dict[str, float] = field(
        default_factory=lambda: {"brier": 0.005, "cost_per_ticket": 0.01}
    )


@dataclass(frozen=True)
class Evaluation:
    """Metrics of candidate, champion and baseline on one common window."""

    window_start: str
    n: int
    candidate: dict[str, float]
    baseline: dict[str, float]
    champion: dict[str, float] | None = None


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    checks: list[Check]

    def summary(self) -> str:
        lines = [f"{'APPROVED' if self.approved else 'REJECTED'}"]
        lines += [f"  [{'ok' if c.passed else 'FAIL'}] {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)


def evaluate_promotion(
    candidate: DeploymentContract,
    champion: DeploymentContract | None,
    evaluation: Evaluation,
    policy: PromotionPolicy | None = None,
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    metric = policy.primary_metric
    checks: list[Check] = []

    violations = contract_violations(candidate)
    checks.append(Check("contract", not violations, "; ".join(violations) or "complete and valid"))

    window = pd.Timestamp(evaluation.window_start)
    seen_until = {"candidate": pd.Timestamp(candidate.dataset.validation_end)}
    if champion is not None:
        seen_until["champion"] = pd.Timestamp(champion.dataset.validation_end)
    overlapping = [name for name, until in seen_until.items() if window < until]
    checks.append(
        Check(
            "unseen_evaluation_window",
            not overlapping,
            f"window starts {window.date()}, n={evaluation.n}"
            + (f"; already used by {overlapping}" if overlapping else ""),
        )
    )

    cand, base = evaluation.candidate[metric], evaluation.baseline[metric]
    checks.append(
        Check(
            "beats_baseline",
            cand > base + policy.min_gain_over_baseline,
            f"{metric} {cand:.4f} vs baseline {base:.4f}",
        )
    )

    if champion is None or evaluation.champion is None:
        checks.append(Check("vs_champion", True, "no current champion (first promotion)"))
    else:
        champ = evaluation.champion[metric]
        checks.append(
            Check(
                "vs_champion",
                cand >= champ + policy.min_improvement,
                f"{metric} {cand:.4f} vs champion {champ:.4f} "
                f"(required >= +{policy.min_improvement})",
            )
        )
        for name, tolerance in policy.guardrails.items():
            c, h = evaluation.candidate[name], evaluation.champion[name]
            checks.append(
                Check(
                    f"guardrail_{name}",
                    c <= h + tolerance,
                    f"{c:.4f} vs champion {h:.4f} (tolerance +{tolerance})",
                )
            )

    return PromotionDecision(approved=all(c.passed for c in checks), checks=checks)
