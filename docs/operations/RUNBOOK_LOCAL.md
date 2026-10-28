# 📘 Runbook de Operación Local: IDCI Platform

Este documento recopila las instrucciones operativas estándar para el levantamiento, prueba, depuración y mantenimiento de la plataforma IDCI en local.

---

## 1. Prerrequisitos

* Docker & Docker Compose v2.
* GNU Make.
* Red Docker `idci_network`.

```bash
make local-network
# o alternativamente:
docker network create idci_network || true
```

---

## 2. Puertos y Accesos

| Servicio | URL / Endpoint Host | Puerto Host | Credenciales por Defecto |
| :--- | :--- | :--- | :--- |
| **Apache Airflow UI** | [http://localhost:8082](http://localhost:8082) | `8082` | `idci_admin` / `secure_password_2026` |
| **PostgreSQL 16** | `localhost:5435` | `5435` | `idci_admin` / `secure_password_2026` / DB: `idci_analytics` |
| **RustFS Web Console** | [http://localhost:9003/rustfs/console/](http://localhost:9003/rustfs/console/) | `9003` | `rustfsadmin` / `rustfsadmin2026` |
| **RustFS S3 API** | `http://localhost:9002` | `9002` | `rustfsadmin` / `rustfsadmin2026` |
| **OpenMetadata** | [http://localhost:8585](http://localhost:8585) | `8585` | Servicio externo / opcional |

---

## 3. Ciclo de Vida del Stack

### Iniciar el Stack Local

```bash
make local-up
# o con Docker Compose:
docker compose -f deploy/local/docker-compose.yml up -d
```

### Consultar Estado de los Servicios

```bash
make local-ps
```

### Inspeccionar Logs

```bash
make local-logs
```

### Detener el Stack (Conservando Volúmenes)

```bash
make local-down
```

### Reinicio Limpio (Eliminando Volúmenes)

```bash
make local-reset
```

---

## 4. Transformaciones dbt Core

Para compilar, ejecutar y validar los modelos dimensionales en PostgreSQL:

```bash
# Ejecutar modelos dbt (staging y silver marts)
make dbt-run

# Ejecutar suite de validaciones de calidad
make dbt-test
```

O utilizando el script dedicado:
```bash
./scripts/local/run_dbt.sh
```

---

## 5. Consultas Útiles en PostgreSQL

Conectar mediante `psql` o cliente SQL (DBeaver, DataGrip, pgAdmin):

```sql
-- Validar conteo de convocatorias en Bronze
SELECT count(*) FROM bronze.idrc__funding_calls;

-- Validar tabla de hechos en Silver
SELECT count(*) FROM silver.fct_opportunities;

-- Consultar la vista consolidada para analítica
SELECT 
    opportunity_code, 
    title, 
    status, 
    closing_date, 
    max_amount, 
    currency 
FROM silver.v_opportunities_consolidated 
LIMIT 10;
```
