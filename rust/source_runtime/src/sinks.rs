//! Destinations the runtime writes to. Real implementations live in `s3`, `pg` and `tika`;
//! the in-memory doubles below serve tests and extractor development without infrastructure.

use std::fmt;
use std::future::Future;

use crate::bronze::{DatasetSpec, Row};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SinkError(pub String);

impl fmt::Display for SinkError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "sink error: {}", self.0)
    }
}

impl std::error::Error for SinkError {}

/// Immutable object storage (`Landing`, RustFS S3).
pub trait LandingSink {
    fn put(&self, key: &str, data: &[u8]) -> impl Future<Output = Result<(), SinkError>> + Send;
    /// Where an object can be found, recorded in bronze as `_landing_uri`.
    fn uri(&self, key: &str) -> String;
}

/// One landed payload, as the records it holds for a typed bronze table.
pub struct BronzeBatch<'a> {
    pub spec: &'a DatasetSpec,
    pub batch_id: &'a str,
    pub landing_uri: &'a str,
    pub rows: &'a [Row],
}

/// PostgreSQL typed `bronze` tables (one per dataset) and the quarantine table.
pub trait BronzeSink {
    /// Loads the batch atomically; loading the same batch again changes nothing.
    fn insert(&self, batch: &BronzeBatch<'_>)
        -> impl Future<Output = Result<(), SinkError>> + Send;
    fn quarantine(
        &self,
        source: &str,
        dataset: &str,
        sha256: &str,
        reason: &str,
    ) -> impl Future<Output = Result<(), SinkError>> + Send;
}

/// Apache Tika Server: plain text from a complex binary.
pub trait TextExtractor {
    fn extract_text(
        &self,
        data: &[u8],
        content_type: Option<&str>,
    ) -> impl Future<Output = Result<String, SinkError>> + Send;
}

/// In-memory doubles for tests and for extractor development without infrastructure.
pub mod memory {
    use super::*;
    use std::collections::BTreeMap;
    use std::sync::Mutex;

    #[derive(Default)]
    pub struct MemoryLanding(pub Mutex<BTreeMap<String, Vec<u8>>>);

    impl LandingSink for MemoryLanding {
        async fn put(&self, key: &str, data: &[u8]) -> Result<(), SinkError> {
            self.0
                .lock()
                .unwrap()
                .insert(key.to_string(), data.to_vec());
            Ok(())
        }

        fn uri(&self, key: &str) -> String {
            format!("memory://{key}")
        }
    }

    /// A stored row: `(keys, batch_id, landing_uri)`.
    pub type MemoryRow = (Vec<String>, String, String);

    /// Rows are kept per table.
    #[derive(Default)]
    pub struct MemoryBronze {
        pub rows: Mutex<BTreeMap<String, Vec<MemoryRow>>>,
        pub quarantined: Mutex<Vec<(String, String)>>,
    }

    impl BronzeSink for MemoryBronze {
        async fn insert(&self, batch: &BronzeBatch<'_>) -> Result<(), SinkError> {
            let mut tables = self.rows.lock().unwrap();
            let table = tables.entry(batch.spec.table.clone()).or_default();
            for row in batch.rows {
                // Same key in the same batch is a no-op, like `ON CONFLICT DO NOTHING`.
                if !table
                    .iter()
                    .any(|(k, b, _)| *k == row.keys && b == batch.batch_id)
                {
                    table.push((
                        row.keys.clone(),
                        batch.batch_id.into(),
                        batch.landing_uri.into(),
                    ));
                }
            }
            Ok(())
        }

        async fn quarantine(
            &self,
            _source: &str,
            _dataset: &str,
            sha256: &str,
            reason: &str,
        ) -> Result<(), SinkError> {
            self.quarantined
                .lock()
                .unwrap()
                .push((sha256.into(), reason.into()));
            Ok(())
        }
    }

    /// Records how many times it was called, so tests can prove Tika was bypassed.
    #[derive(Default)]
    pub struct CountingTika {
        pub calls: Mutex<usize>,
    }

    impl TextExtractor for CountingTika {
        async fn extract_text(
            &self,
            _data: &[u8],
            _content_type: Option<&str>,
        ) -> Result<String, SinkError> {
            *self.calls.lock().unwrap() += 1;
            Ok("extracted text".to_string())
        }
    }
}
