# Ingesta y Spiders: Convocatorias IDCI / IDRC

## Spider Especializado

El motor de extracción ejecuta la araña especializada registrada bajo `src/extractor/spiders/`:

| Spider | Nombre | URL por Defecto | Tabla Destino Bronze | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `idci` (`idrc`) | IDCI / IDRC Funding | `https://idrc-crdi.ca/en/funding` | `bronze.idrc__funding_calls` | Portal oficial de oportunidades del International Development Research Centre (IDRC / IDCI Canadá). |

---

## Ejecución Manual (CLI de Contenedor)

### 1. Etapa de Extracción (Web -> RustFS S3)

```bash
docker run --rm --network idci_network \
  -e S3_ENDPOINT_URL="http://rustfs:9000" \
  -e S3_ACCESS_KEY="rustfsadmin" \
  -e S3_SECRET_KEY="rustfsadmin2026" \
  -e S3_BUCKET="opportunity-intelligence" \
  idci_scraper:latest --step extract --spider idci --limit 50
```

### 2. Etapa de Procesamiento Fan-Out Tika (Landing -> Processed Zone)

```bash
# Consultar plan de particionamiento
docker run --rm --network idci_network \
  -e S3_ENDPOINT_URL="http://rustfs:9000" \
  -e S3_ACCESS_KEY="rustfsadmin" \
  -e S3_SECRET_KEY="rustfsadmin2026" \
  -e S3_BUCKET="opportunity-intelligence" \
  idci_tika:latest --plan --chunk-size 500 --institution idrc

# Ejecutar un lote específico
docker run --rm --network idci_network \
  -e S3_ENDPOINT_URL="http://rustfs:9000" \
  -e S3_ACCESS_KEY="rustfsadmin" \
  -e S3_SECRET_KEY="rustfsadmin2026" \
  -e S3_BUCKET="opportunity-intelligence" \
  idci_tika:latest --chunk-id "Lote-1" --offset 0 --limit 500 --institution idrc
```

### 3. Etapa de Carga (RustFS S3 -> PostgreSQL Bronze)

```bash
docker run --rm --network idci_network \
  -e POSTGRES_HOST="postgres" \
  -e POSTGRES_PORT="5432" \
  -e POSTGRES_USER="idci_admin" \
  -e POSTGRES_PASSWORD="secure_password_2026" \
  -e POSTGRES_DB="idci_analytics" \
  -e S3_ENDPOINT_URL="http://rustfs:9000" \
  -e S3_ACCESS_KEY="rustfsadmin" \
  -e S3_SECRET_KEY="rustfsadmin2026" \
  -e S3_BUCKET="opportunity-intelligence" \
  idci_loader:latest --step load --spider idci
```
