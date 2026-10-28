# ==============================================================================
# IDCI Platform - Makefile
# Automatización de tareas locales siguiendo estándares de CEDIA Data Architecture
# ==============================================================================

COMPOSE_FILE := deploy/local/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)
DOCKER_NETWORK := idci_network

.PHONY: help local-network local-up local-down local-ps local-logs local-reset \
	dbt-run dbt-test dbt-build test docker-build postgres-shell

help:
	@echo "Comandos disponibles en IDCI Platform:"
	@echo "  make local-up         Levanta el stack local completo (PostgreSQL, RustFS S3, Airflow)"
	@echo "  make local-down       Detiene los contenedores locales (conserva volúmenes)"
	@echo "  make local-ps         Muestra el estado de los contenedores locales"
	@echo "  make local-logs       Muestra los logs en tiempo real del stack"
	@echo "  make local-reset      Detiene y ELIMINA todos los volúmenes locales (datos crudos y warehouse)"
	@echo "  make local-network    Crea la red Docker idci_network si no existe"
	@echo "  make dbt-run          Ejecuta transformaciones dbt Core en contenedor efímero (--rm)"
	@echo "  make dbt-test         Ejecuta la suite de pruebas de calidad dbt Core (--rm)"
	@echo "  make dbt-build        Ejecuta dbt build completo (modelos + tests)"
	@echo "  make docker-build     Construye las imágenes efímeras (scraper, tika, dbt, metadata)"
	@echo "  make postgres-shell   Abre una sesión interactiva psql en el contenedor de PostgreSQL"
	@echo "  make test             Ejecuta los tests unitarios"

local-network:
	@bash scripts/local/setup_network.sh

local-up: local-network
	$(COMPOSE) up -d
	@echo "✅ Stack IDCI iniciado exitosamente."
	@echo "  - Airflow UI:   http://localhost:8082"
	@echo "  - PostgreSQL:   localhost:5435"
	@echo "  - RustFS S3:    http://localhost:9002 (API) / http://localhost:9003 (UI)"

local-down:
	$(COMPOSE) down

local-ps:
	$(COMPOSE) ps

local-logs:
	$(COMPOSE) logs -f

local-reset:
	$(COMPOSE) down -v
	@echo "⚠️ Todos los volúmenes de datos locales han sido eliminados."

dbt-run:
	@bash scripts/local/run_dbt.sh

dbt-test:
	$(COMPOSE) run --rm dbt test --profiles-dir . --target docker

dbt-build:
	$(COMPOSE) run --rm dbt build --profiles-dir . --target docker

docker-build:
	$(COMPOSE) build

postgres-shell:
	docker exec -it idci_postgres psql -U idci_admin -d idci_analytics

test:
	pytest tests/ || python3 -m unittest discover -s tests -p "test_*.py"
