# Airflow with the `scrapagents` package, so generated DAGs can run its extractors and checks.
# Build context: repository root (see .dockerignore).
ARG AIRFLOW_VERSION=3.4.0
# Python 3.12 is the interpreter validated with dbt-core 1.12.3. dbt lives in its own virtualenv so its
# pins never clash with Airflow's.
ARG AIRFLOW_PYTHON=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${AIRFLOW_PYTHON}

USER root
COPY dbt/requirements.txt /tmp/dbt-requirements.txt
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir -r /tmp/dbt-requirements.txt \
    && chown -R airflow:0 /opt/dbt-venv \
    && rm /tmp/dbt-requirements.txt
USER airflow

COPY --chown=airflow:0 pyproject.toml /tmp/scrapagents/pyproject.toml
COPY --chown=airflow:0 python/scrapagents /tmp/scrapagents/python/scrapagents
RUN pip install --no-cache-dir "/tmp/scrapagents[extractors]" && rm -rf /tmp/scrapagents

# Contracts and source declarations read by the extractors (SCRAPAGENTS_CONFIG_ROOT=/opt/scrapagents).
COPY --chown=airflow:0 configs /opt/scrapagents/configs

# Payloads of the harness-only fixture source (ingestions/_fixture).
COPY --chown=airflow:0 python/tests/fixtures /opt/scrapagents/fixtures
