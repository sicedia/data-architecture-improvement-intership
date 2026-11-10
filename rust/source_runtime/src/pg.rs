//! `BronzeSink` over PostgreSQL: typed `bronze.<source>__<dataset>` tables and the quarantine table.

use deadpool_postgres::{Config, Pool, Runtime};
use serde_json::{json, Value};
use tokio_postgres::NoTls;

use crate::sinks::{BronzeBatch, BronzeSink, SinkError};

pub struct PgBronze {
    pool: Pool,
}

fn err(context: &str, e: impl std::fmt::Display) -> SinkError {
    SinkError(format!("{context}: {e}"))
}

impl PgBronze {
    pub fn connect(database_url: &str) -> Result<Self, SinkError> {
        let cfg = Config {
            url: Some(database_url.to_string()),
            ..Config::default()
        };
        let pool = cfg
            .create_pool(Some(Runtime::Tokio1), NoTls)
            .map_err(|e| err("postgres pool", e))?;
        Ok(Self { pool })
    }

    /// Fail fast at start-up when the warehouse is unreachable.
    pub async fn ping(&self) -> Result<(), SinkError> {
        let client = self.pool.get().await.map_err(|e| err("postgres", e))?;
        client
            .simple_query("SELECT 1")
            .await
            .map_err(|e| err("postgres", e))?;
        Ok(())
    }
}

/// Table and column names are validated when the registry loads (`[A-Za-z0-9_]` only); they are
/// still quoted so they can never be read as anything but an identifier.
fn quoted(name: &str) -> String {
    format!("\"{name}\"")
}

/// One statement per batch: the rows travel as a JSON array and are unpacked by PostgreSQL, so the
/// whole batch is atomic and a replay (same `_batch_id`, same keys) inserts nothing.
fn insert_sql(table: &str, keys: &[String]) -> String {
    let key_columns: Vec<String> = keys.iter().map(|k| quoted(k)).collect();
    let key_values: Vec<String> = (0..keys.len())
        .map(|i| format!("e.v->'keys'->>{i}"))
        .collect();
    format!(
        "INSERT INTO bronze.{table} ({columns}, payload, _batch_id, _landing_uri, _record_hash) \
         SELECT {values}, e.v->'payload', $2::text::uuid, $3::text, e.v->>'hash' \
         FROM jsonb_array_elements($1::jsonb) AS e(v) \
         ON CONFLICT DO NOTHING",
        table = quoted(table),
        columns = key_columns.join(", "),
        values = key_values.join(", "),
    )
}

impl BronzeSink for PgBronze {
    async fn insert(&self, batch: &BronzeBatch<'_>) -> Result<(), SinkError> {
        if batch.rows.is_empty() {
            return Ok(());
        }
        let rows: Vec<Value> = batch
            .rows
            .iter()
            .map(|r| json!({ "keys": r.keys, "payload": r.payload, "hash": r.record_hash }))
            .collect();
        let rows = Value::Array(rows);
        let sql = insert_sql(&batch.spec.table, &batch.spec.keys);
        let client = self.pool.get().await.map_err(|e| err("postgres", e))?;
        client
            .execute(&sql, &[&rows, &batch.batch_id, &batch.landing_uri])
            .await
            .map_err(|e| err(&format!("insert bronze.{}", batch.spec.table), e))?;
        Ok(())
    }

    async fn quarantine(
        &self,
        source: &str,
        dataset: &str,
        sha256: &str,
        reason: &str,
    ) -> Result<(), SinkError> {
        let client = self.pool.get().await.map_err(|e| err("postgres", e))?;
        client
            .execute(
                "INSERT INTO bronze_quarantine.rejected_payloads (source, dataset, sha256, reason) \
                 VALUES ($1, $2, $3, $4) ON CONFLICT (source, dataset, sha256) DO NOTHING",
                &[&source, &dataset, &sha256, &reason],
            )
            .await
            .map_err(|e| err("insert quarantine", e))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn insert_sql_unpacks_keys_in_declared_order_and_ignores_replays() {
        let sql = insert_sql("demo__people", &["id".into(), "Org_Code".into()]);
        assert!(sql.starts_with(
            "INSERT INTO bronze.\"demo__people\" (\"id\", \"Org_Code\", payload, _batch_id, \
             _landing_uri, _record_hash)"
        ));
        assert!(sql.contains("e.v->'keys'->>0, e.v->'keys'->>1"));
        assert!(sql.ends_with("ON CONFLICT DO NOTHING"));
    }
}
