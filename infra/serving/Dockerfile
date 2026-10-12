# Imagen del servicio de predicción (contexto de build: raíz del repositorio).
#
# Dos etapas: la primera instala las dependencias EXACTAS de uv.lock; la segunda copia solo
# el entorno resultante, sin uv ni cachés.
#
# Las dependencias (~500 MB) y el código (~1 MB) van en capas separadas: un cambio de código
# solo reconstruye la capa pequeña. Si el paquete se instalara dentro del entorno, cada cambio
# de código generaría otra capa de ~500 MB (y llenaría el disco de imágenes huérfanas).

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /app/.venv /app/.venv
COPY src /app/src
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER app
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# Sin access log de uvicorn: la API escribe su propio log estructurado con latencia.
CMD ["uvicorn", "use_cases.sla_risk.serving:app_factory", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
