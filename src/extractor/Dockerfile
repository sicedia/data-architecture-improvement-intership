FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python (incluyendo Playwright)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium headless y dependencias del sistema de Playwright
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno para ejecución segura en contenedores
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright \
    USE_PLAYWRIGHT=true

# Copiar paquete modular de spiders y entrypoint
COPY spiders/ /app/spiders/
COPY scraper.py /app/scraper.py

# Entrypoint estándar
ENTRYPOINT ["python3", "/app/scraper.py"]
CMD ["--step", "all"]
