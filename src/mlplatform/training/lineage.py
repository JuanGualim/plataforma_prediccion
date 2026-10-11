"""Trazabilidad: con qué código y qué entorno se entrenó un modelo.

Es el embrión del contrato de despliegue (fase 3): un modelo sin commit conocido no se
puede reproducir ni auditar.
"""

import platform
import subprocess
from importlib.metadata import version
from pathlib import Path


def git_info(repo_dir: Path | None = None) -> dict[str, str | bool | None]:
    """Current commit and whether there were uncommitted changes (dirty)."""

    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo_dir, capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return out.stdout.strip()

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def environment_info(packages: tuple[str, ...] = ("scikit-learn", "pandas", "numpy")) -> dict:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in packages},
    }
