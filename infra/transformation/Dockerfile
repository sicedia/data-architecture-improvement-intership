# dbt toolbox image. Build context: repository root (see .dockerignore).
FROM python:3.12-slim
COPY dbt/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
WORKDIR /dbt
ENTRYPOINT ["dbt"]
