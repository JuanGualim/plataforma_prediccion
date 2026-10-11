import pytest

from use_cases.sla_risk.simulator import SimulationConfig, SimulationResult, simulate

SMALL_CONFIG = SimulationConfig(days=28, tickets_per_day=60, seed=7)


@pytest.fixture(scope="session")
def small_config() -> SimulationConfig:
    return SMALL_CONFIG


@pytest.fixture(scope="session")
def small_sim() -> SimulationResult:
    """A small but complete simulation shared by tests (deterministic)."""
    return simulate(SMALL_CONFIG)
