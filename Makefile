SHELL := /bin/bash
# Python >= 3.11. With uv: `uv venv --python 3.13 .venv && uv pip install -e ".[dev,extractors]"`.
PYTHON ?= python3.13
VENV ?= .venv
VPY := $(VENV)/bin/python
# One compose project per domain, in start order. F4/F6 add transformation, governance.
STACKS ?= warehouse ingestion orchestration
# Tool stacks (no long-running services); `make dbt CMD=...` runs dbt in the transformation stack.
TOOL_STACKS := transformation
DBT_CONTRACTS ?= ingestions/_fixture/contracts/records.yml
# Sources that get a generated DAG: the harness fixture plus every configs/ingestions/<id>.yml.
DAG_CONFIGS ?= ingestions/_fixture/ingestion.yml
CONFIG_IDS := $(patsubst %.yml,%,$(notdir $(wildcard configs/ingestions/*.yml)))
IDS ?= $(CONFIG_IDS)
# Contracts of configs/contracts/<source>/<dataset>.yml as <source>/<dataset>.
CATALOG_CONTRACTS := $(foreach f,$(wildcard configs/contracts/*/*.yml),$(notdir $(patsubst %/,%,$(dir $(f))))/$(basename $(notdir $(f))))
AIRFLOW_VERSION ?= 3.4.0
AIRFLOW_PYTHON ?= 3.12
export AIRFLOW_VERSION AIRFLOW_PYTHON
NETWORK := scrapagents_net
COMPOSE ?= docker compose

.PHONY: help setup new-ingestion check-gates check-contracts lint test \
	rust-build rust-test smoke smoke-f3 generate-dags check-dags airflow-parse airflow-pools \
	generate-dbt check-dbt status advance review probe sign generate-bronze check-bronze bronze-apply dbt dbt-parse dbt-check-catalog infra-env infra-network infra-up infra-down infra-config validate

help:
	@echo "make setup                         venv + dev and extractor dependencies"
	@echo "make new-ingestion ID= TEAM= [DATASET=records] [TYPE=api|database|file|web]"
	@echo "                                   design-time dossier in ingestions/<id>/"
	@echo "make check-gates                   human gates H1/H2/PR respected in every dossier"
	@echo "make status|advance|review|probe ID=<id>   design-time workflow of one source (agents)"
	@echo "make sign ID=<id> GATE=h1|h2|pr BY=<you>     HUMAN ONLY: sign a gate in your own terminal"
	@echo "make check-contracts               configs/contracts and dossier drafts are valid"
	@echo "make lint | test                   ruff | pytest"
	@echo "make rust-build | rust-test        native SourceRuntime"
	@echo "make infra-up | infra-down         docker stacks: warehouse (PostgreSQL), ingestion (RustFS, Tika)"
	@echo "                                   one stack: make infra-up STACKS=ingestion"
	@echo "make generate-dags | check-dags generate the YAML DAGs into dags/ | fail if they drifted from their sources"
	@echo "make airflow-pools                 re-import dags/_pools.json into a running Airflow (needed after new sources)"
	@echo "make airflow-parse                 load every generated DAG in dags/ in Airflow $(AIRFLOW_VERSION)"
	@echo "make smoke-f3                      F3 end-to-end: Airflow YAML DAG -> RustWorker (all stacks up)"
	@echo "make smoke                         F2 end-to-end: fixture extractor -> RustWorker -> RustFS/bronze/Tika"
	@echo "make validate                      lint, test, rust-test, gates, contracts"

setup:
	$(PYTHON) -m venv $(VENV)
	$(VPY) -m pip install -q -e ".[dev,extractors]"

new-ingestion:
	@test -n "$(ID)" -a -n "$(TEAM)" || { echo "usage: make new-ingestion ID=<id> TEAM=<team>"; exit 2; }
	$(VPY) scripts/new_ingestion.py --id "$(ID)" --team "$(TEAM)" --dataset "$(or $(DATASET),records)" --type "$(or $(TYPE),api)"

check-gates:
	$(VPY) -m scrapagents.cli check-gates

check-contracts:
	$(VPY) -m scrapagents.cli check-contracts

lint:
	$(VPY) -m ruff check python scripts

test:
	$(VPY) -m pytest

rust-build:
	cd rust/source_runtime && cargo build --release

rust-test:
	cd rust/source_runtime && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

infra-env:
	@test -f .env || cp .env.example .env
	@# Keep a copy for scripts that still look under infra/ (apply_bronze, older notes).
	@mkdir -p infra && cp .env infra/.env

smoke:
	@$(MAKE) --no-print-directory infra-up
	@for i in $$(seq 1 30); do curl -sf http://127.0.0.1:8088/healthz >/dev/null && break; sleep 2; done
	$(VPY) -m pytest python/tests/test_smoke_f2.py -rs

smoke-f3: infra-up
	@for i in $$(seq 1 60); do \
		c=$$(docker ps --format '{{.Names}}' | grep -E 'scrapagents.*airflow-api-server' | head -n 1); \
		test -n "$$c" && docker exec "$$c" python -c "import urllib.request as u; u.urlopen('http://localhost:8080/api/v2/monitor/health', timeout=3)" >/dev/null 2>&1 && break; sleep 3; \
	done
	$(VPY) -m pytest python/tests/test_smoke_f3.py -rs

# Design-time workflow of one source (see .claude/skills/new-source). ID=<ingestion id>
status:
	$(VPY) -m scrapagents.cli status --id $(ID)

advance:
	$(VPY) -m scrapagents.cli advance --id $(ID)

review:
	$(VPY) -m scrapagents.cli review --id $(ID)

# make probe ID=<id> URL="https://a https://b"   (browser: needs `pip install .[probes]` and OBSCURA_CDP_URL)
probe:
	$(VPY) -m scrapagents.cli probe --id $(ID) $(foreach u,$(URL),--url $(u))

# HUMAN ONLY, in your own terminal: make sign ID=<id> GATE=h1 BY="Your Name"
sign:
	$(VPY) -m scrapagents.cli sign --id $(ID) --gate $(GATE) --by "$(BY)"

generate-dags:
	$(VPY) -m scrapagents.cli generate-dags $(foreach c,$(DAG_CONFIGS),--config $(c)) $(foreach i,$(IDS),--id $(i))

check-dags:
	$(VPY) -m scrapagents.cli generate-dags --check $(foreach c,$(DAG_CONFIGS),--config $(c)) $(foreach i,$(IDS),--id $(i))

airflow-parse:
	scripts/check_airflow_dags.sh dags

# Pools are written to dags/_pools.json by generate-dags, but Airflow only loads them at
# airflow-init (or via this target). Without this, land__* tasks wait forever on a missing pool.
airflow-pools:
	@docker exec scrapagents-airflow-api-server \
		airflow pools import /opt/airflow/dags/_pools.json

generate-bronze:
	$(VPY) -m scrapagents.cli generate-bronze $(foreach c,$(DBT_CONTRACTS),--contract $(c)) $(foreach c,$(CATALOG_CONTRACTS),--catalog $(c))

check-bronze:
	$(VPY) -m scrapagents.cli generate-bronze --check $(foreach c,$(DBT_CONTRACTS),--contract $(c)) $(foreach c,$(CATALOG_CONTRACTS),--catalog $(c))

# Creates the typed bronze tables in the running warehouse (idempotent) and reloads the registry.
bronze-apply: infra-env
	./scripts/apply_bronze.sh bronze/tables.sql
	@c=$$(docker ps --format '{{.Names}}' | grep -E 'scrapagents.*source-runtime' | head -n 1); \
	test -n "$$c" && docker restart "$$c" >/dev/null 2>&1 || true

generate-dbt:
	$(VPY) -m scrapagents.cli generate-dbt $(foreach c,$(DBT_CONTRACTS),--contract $(c)) $(foreach c,$(CATALOG_CONTRACTS),--catalog $(c))

check-dbt:
	$(VPY) -m scrapagents.cli generate-dbt --check $(foreach c,$(DBT_CONTRACTS),--contract $(c)) $(foreach c,$(CATALOG_CONTRACTS),--catalog $(c))

# make dbt CMD="build --select tag:source_fixture"   (needs the warehouse stack: make infra-up)
dbt: infra-env infra-network
	$(COMPOSE) --profile tools run --rm dbt $(or $(CMD),build)

dbt-parse:
	@$(MAKE) --no-print-directory dbt CMD=parse

# Builds generated models for every contract of configs/contracts in a throw-away database (needs the warehouse stack).
dbt-check-catalog: infra-env infra-network
	$(COMPOSE) --profile tools build dbt
	./scripts/check_dbt_catalog.sh

infra-network:
	@docker network inspect $(NETWORK) >/dev/null 2>&1 || docker network create $(NETWORK)

infra-up: infra-env infra-network
	$(COMPOSE) up -d --build
	@./scripts/apply_bronze.sh bronze/tables.sql || exit 1
	@$(MAKE) --no-print-directory airflow-pools || true

infra-down:
	$(COMPOSE) down -v --remove-orphans || true

infra-config: infra-env
	$(COMPOSE) --profile tools config --quiet || exit 1

validate: lint test rust-test check-gates check-contracts check-dags check-dbt check-bronze infra-config
