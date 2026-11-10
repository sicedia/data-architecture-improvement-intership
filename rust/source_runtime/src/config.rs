//! Runtime configuration, read once from the environment (no dynamic behaviour at run-time).

use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub bind: String,
    pub s3_endpoint: String,
    pub s3_bucket: String,
    pub s3_access_key: String,
    pub s3_secret_key: String,
    pub database_url: String,
    pub tika_url: String,
    pub max_body_bytes: usize,
    /// Design-time `bronze/registry.json`; without it no dataset has a typed bronze table.
    pub bronze_registry: Option<String>,
}

fn required(name: &str) -> Result<String, String> {
    env::var(name).map_err(|_| format!("missing environment variable {name}"))
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        Ok(Self {
            bind: env::var("RUNTIME_BIND").unwrap_or_else(|_| "0.0.0.0:8088".into()),
            s3_endpoint: required("S3_ENDPOINT")?,
            s3_bucket: env::var("S3_BUCKET").unwrap_or_else(|_| "landing".into()),
            s3_access_key: required("S3_ACCESS_KEY")?,
            s3_secret_key: required("S3_SECRET_KEY")?,
            database_url: required("DATABASE_URL")?,
            tika_url: required("TIKA_URL")?,
            max_body_bytes: env::var("RUNTIME_MAX_BODY_BYTES")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(256 * 1024 * 1024),
            bronze_registry: env::var("BRONZE_REGISTRY").ok().filter(|v| !v.is_empty()),
        })
    }
}
