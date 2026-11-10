# ScrapAgents

Design-time harness and deterministic run-time for the Producto OI data platform. It runs entirely on this machine and is independent of CEDIA. Architecture and rules: [AGENTS.md](AGENTS.md).
Plan by phase: [docs/implementation-plan.md](docs/implementation-plan.md). Notes on how it differs from CEDIA (reference only):
[docs/cedia-alignment.md](docs/cedia-alignment.md).

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e ".[dev,extractors]"
make validate                                          # lint, pytest, cargo, gates, contracts, compose
make new-ingestion ID=world_bank TEAM=iditi            # design-time dossier in ingestions/world_bank/
make infra-up                                          # warehouse (PostgreSQL) + ingestion (RustFS, Tika, RustWorker); needs Docker
make generate-dags && make airflow-parse                     # declarative YAML DAGs -> loaded by Airflow 3.4.0
make smoke-f3                                          # F3/F4 end-to-end: Airflow -> RustWorker -> dbt (all stacks up)
make status|advance|review|probe ID=<id>               # F5 design-time workflow of a source (agents call these)
make sign ID=<id> GATE=h1|h2|pr BY="Your Name"         # HUMAN ONLY: sign a gate in your own terminal
make generate-bronze / check-bronze                      # typed bronze DDL + runtime registry from contracts
make bronze-apply                                      # create the typed bronze tables in the running warehouse
make generate-dbt / check-dbt                          # dbt sources/models from contracts / drift check
make dbt-check-catalog                                 # build models of every contract in configs/ in a scratch DB
make smoke                                             # F2 end-to-end (needs `.[smoke]`: pip install -e ".[dev,smoke]")
```

Rust is required for `make rust-test` (`rustup`, stable).
