FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests psycopg2-binary pyyaml

COPY . /app/

ENTRYPOINT ["python3", "/app/lineage_validator.py"]
