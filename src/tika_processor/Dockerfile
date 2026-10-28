FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema y JRE Headless para Apache Tika
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-descargar y pre-calentar Apache Tika Server en /tmp durante la construcción de la imagen
RUN python3 -c "import tika; from tika import parser; parser.from_buffer('idci-tika-init')"

# Configurar variables de entorno
ENV PYTHONUNBUFFERED=1 \
    TIKA_SERVER_JAR=/tmp/tika-server.jar

# Copiar script de procesamiento Fan-Out
COPY processor.py /app/processor.py

ENTRYPOINT ["python3", "/app/processor.py"]
CMD ["--help"]
