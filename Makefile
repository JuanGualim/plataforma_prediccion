# Punto de entrada único para operar el proyecto. `make help` lista los comandos.
.DEFAULT_GOAL := help
.PHONY: help env setup up down logs psql db-reset lint format test test-integration \
        data baseline train promote rollback models serve clean

UV ?= uv

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Entorno -----------------------------------------------------------------
env: ## Crea .env a partir de .env.example (si no existe)
	@test -f .env || (cp .env.example .env && echo ".env creado")

setup: env ## Instala Python 3.12 y dependencias (incluye dev) con uv
	$(UV) sync

# --- Infraestructura ---------------------------------------------------------
up: env ## Levanta los servicios (fase 1: PostgreSQL) y espera a que estén sanos
	docker compose up -d --wait

down: ## Detiene los servicios (conserva los datos)
	docker compose down

logs: ## Muestra logs de los servicios
	docker compose logs -f

psql: ## Abre una consola psql dentro del contenedor
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-reset: ## BORRA el volumen de Postgres y lo recrea (re-ejecuta los scripts de init)
	docker compose down -v
	docker compose up -d --wait

# --- Calidad -----------------------------------------------------------------
lint: ## Revisa estilo y errores con ruff
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Formatea el código con ruff
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test: ## Pruebas unitarias (no requieren servicios)
	$(UV) run pytest -m "not integration"

test-integration: ## Pruebas de integración (requieren `make up`)
	$(UV) run pytest -m integration

# --- Ciclo de vida del modelo --------------------------------------------------
data: ## [Fase 1] Genera tickets sintéticos y los carga en Postgres (ARGS="--days 210 --as-of ...")
	$(UV) run python -m use_cases.sla_risk.simulate $(ARGS)

baseline: ## [Fase 1] Evalúa los baselines del modelo de SLA (requiere `make data`)
	$(UV) run python -m use_cases.sla_risk.run_baseline

train: ## [Fase 2-3] Entrena, evalúa y registra un candidato en MLflow (ARGS="--candidates ...")
	$(UV) run python -m use_cases.sla_risk.train $(ARGS)

promote: ## [Fase 3] Pasa un candidato por la puerta de promoción (VERSION=n, REASON="...")
	$(UV) run python -m use_cases.sla_risk.registry_cli promote \
		$(if $(VERSION),--version $(VERSION)) $(if $(REASON),--reason "$(REASON)")

rollback: ## [Fase 3] Devuelve champion a la versión anterior (REASON="..." obligatorio)
	@test -n "$(REASON)" || (echo 'Falta el motivo: make rollback REASON="..."' && exit 1)
	$(UV) run python -m use_cases.sla_risk.registry_cli rollback --reason "$(REASON)"

models: ## [Fase 3] Muestra versiones, champion y últimos eventos del registry
	$(UV) run python -m use_cases.sla_risk.registry_cli status

serve: ## [Fase 4] Levanta la API de predicción
	@echo "Pendiente (fase 4): serving con FastAPI"

# --- Limpieza ----------------------------------------------------------------
clean: ## Borra cachés locales (no toca datos ni volúmenes)
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
