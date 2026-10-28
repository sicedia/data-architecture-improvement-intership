FROM python:3.10-slim

WORKDIR /usr/app/dbt

# Instalar dependencias del sistema mínimas (incluyendo libpq5 para postgres)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Instalar dbt-postgres
RUN pip install --no-cache-dir dbt-postgres==1.8.2

ENV DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true

# Copiar el código del proyecto dbt al contenedor
COPY . /usr/app/dbt

ENTRYPOINT ["dbt"]
CMD ["run", "--profiles-dir", ".", "--target", "docker"]
