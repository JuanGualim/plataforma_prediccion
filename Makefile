# Punto de entrada único para operar el proyecto. `make help` lista los comandos.
.DEFAULT_GOAL := help
.PHONY: help env setup up down logs psql db-reset lint format test test-integration \
        data baseline train promote rollback serve clean

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
data: ## [Fase 1] Genera tickets sintéticos, los valida y los carga en Postgres (requiere `make up`)
	$(UV) run python -m use_cases.sla_risk.simulate

baseline: ## [Fase 1] Evalúa los baselines del modelo de SLA (requiere `make data`)
	$(UV) run python -m use_cases.sla_risk.run_baseline

train: ## [Fase 2] Entrena el modelo de riesgo de SLA
	@echo "Pendiente (fase 2): entrenamiento"

promote: ## [Fase 3] Evalúa un candidato contra el champion y lo promueve si pasa la puerta
	@echo "Pendiente (fase 3): puerta de promoción"

rollback: ## [Fase 3] Devuelve el alias champion a la versión anterior
	@echo "Pendiente (fase 3): rollback"

serve: ## [Fase 4] Levanta la API de predicción
	@echo "Pendiente (fase 4): serving con FastAPI"

# --- Limpieza ----------------------------------------------------------------
clean: ## Borra cachés locales (no toca datos ni volúmenes)
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
