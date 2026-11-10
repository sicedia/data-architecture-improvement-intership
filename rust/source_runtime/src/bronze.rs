//! Typed bronze: one table per dataset, `bronze.<source>__<dataset>`, the shape CEDIA uses.
//!
//! Which datasets have a table, and which columns form their key, is decided at design time and
//! written to `bronze/registry.json` by `scrapagents generate-bronze` (from the data contracts).
//! The runtime only reads that file: no table name or key ever comes from a payload.
//!
//! A table holds the key columns (TEXT), the record as `payload` (JSONB) and the lineage columns
//! `_ingested_at`, `_batch_id`, `_landing_uri` and `_record_hash`. A landed payload is one batch;
//! its id is derived from the payload SHA-256, so loading the same bytes twice adds nothing.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

/// Physical column names a key can not use.
pub const RESERVED_COLUMNS: [&str; 5] = [
    "payload",
    "_ingested_at",
    "_batch_id",
    "_landing_uri",
    "_record_hash",
];

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct DatasetSpec {
    pub table: String,
    pub keys: Vec<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Registry {
    datasets: BTreeMap<String, DatasetSpec>,
}

#[derive(Deserialize)]
struct RegistryFile {
    datasets: BTreeMap<String, DatasetSpec>,
}

fn is_table(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && b.len() <= 54
        && (b[0].is_ascii_lowercase() || b[0] == b'_')
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_')
}

fn is_column(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && (b[0].is_ascii_alphabetic() || b[0] == b'_')
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_')
}

impl Registry {
    pub fn from_json(text: &str) -> Result<Self, String> {
        let file: RegistryFile =
            serde_json::from_str(text).map_err(|e| format!("bronze registry: {e}"))?;
        let mut tables = BTreeSet::new();
        for (id, spec) in &file.datasets {
            if id.split('/').count() != 2 {
                return Err(format!(
                    "bronze registry: {id:?} must be <source>/<dataset>"
                ));
            }
            if !is_table(&spec.table) {
                return Err(format!("bronze registry: {id}: invalid table name"));
            }
            if !tables.insert(spec.table.clone()) {
                return Err(format!(
                    "bronze registry: table {} is used twice",
                    spec.table
                ));
            }
            if spec.keys.is_empty() {
                return Err(format!("bronze registry: {id}: at least one key column"));
            }
            for key in &spec.keys {
                if !is_column(key) || RESERVED_COLUMNS.contains(&key.as_str()) {
                    return Err(format!("bronze registry: {id}: invalid key column {key:?}"));
                }
            }
        }
        Ok(Self {
            datasets: file.datasets,
        })
    }

    pub fn from_file(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("bronze registry {}: {e}", path.display()))?;
        Self::from_json(&text)
    }

    pub fn get(&self, source: &str, dataset: &str) -> Option<&DatasetSpec> {
        self.datasets.get(&format!("{source}/{dataset}"))
    }

    pub fn len(&self) -> usize {
        self.datasets.len()
    }

    pub fn is_empty(&self) -> bool {
        self.datasets.is_empty()
    }
}

/// One record ready to load.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Row {
    pub keys: Vec<String>,
    pub payload: Value,
    pub record_hash: String,
}

/// UUID derived from the payload hash: the same bytes always make the same batch.
pub fn batch_id(sha256: &str) -> String {
    let h = &sha256[..32];
    format!(
        "{}-{}-{}-{}-{}",
        &h[0..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..32]
    )
}

fn record_hash(record: &Value) -> String {
    // serde_json keeps object keys sorted, so the serialization is canonical.
    let bytes = serde_json::to_vec(record).expect("a JSON value always serializes");
    let digest = Sha256::digest(bytes);
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

fn key_text(record: &Value, key: &str) -> Option<String> {
    match record.get(key)? {
        Value::String(s) if !s.trim().is_empty() => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

/// Records of a landed JSON document: an array, `{"records": [...]}` or a single object.
fn records(doc: &Value) -> Vec<&Value> {
    match doc {
        Value::Array(items) => items.iter().collect(),
        Value::Object(map) => match map.get("records") {
            Some(Value::Array(items)) => items.iter().collect(),
            _ => vec![doc],
        },
        _ => Vec::new(),
    }
}

/// Rows of a payload for a dataset. Any invalid record rejects the whole payload (CEDIA's default,
/// `max_reject_percentage: 0`): the bytes stay in Landing and the payload goes to quarantine.
pub fn extract_rows(spec: &DatasetSpec, doc: &Value) -> Result<Vec<Row>, String> {
    if !matches!(doc, Value::Array(_) | Value::Object(_)) {
        return Err("payload is not a JSON array or object of records".into());
    }
    let mut seen = BTreeSet::new();
    let mut rows = Vec::new();
    for (n, record) in records(doc).into_iter().enumerate() {
        if !record.is_object() {
            return Err(format!("record {n} is not a JSON object"));
        }
        let mut keys = Vec::with_capacity(spec.keys.len());
        for key in &spec.keys {
            match key_text(record, key) {
                Some(value) => keys.push(value),
                None => return Err(format!("record {n}: missing or empty key {key:?}")),
            }
        }
        if !seen.insert(keys.clone()) {
            return Err(format!("record {n}: duplicate key {keys:?} in the batch"));
        }
        rows.push(Row {
            keys,
            payload: record.clone(),
            record_hash: record_hash(record),
        });
    }
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn spec(keys: &[&str]) -> DatasetSpec {
        DatasetSpec {
            table: "demo__people".into(),
            keys: keys.iter().map(|k| k.to_string()).collect(),
        }
    }

    #[test]
    fn registry_loads_and_looks_datasets_up() {
        let r = Registry::from_json(
            r#"{"datasets": {"demo/people": {"table": "demo__people", "keys": ["id"]}}}"#,
        )
        .unwrap();
        assert_eq!(r.get("demo", "people").unwrap().keys, ["id"]);
        assert!(r.get("demo", "other").is_none());
        assert_eq!(r.len(), 1);
    }

    #[test]
    fn registry_rejects_unsafe_or_ambiguous_entries() {
        let bad = [
            r#"{"datasets": {"demo/p": {"table": "bronze.x; drop", "keys": ["id"]}}}"#,
            r#"{"datasets": {"demo/p": {"table": "t", "keys": []}}}"#,
            r#"{"datasets": {"demo/p": {"table": "t", "keys": ["a\"b"]}}}"#,
            r#"{"datasets": {"demo/p": {"table": "t", "keys": ["_batch_id"]}}}"#,
            r#"{"datasets": {"demo": {"table": "t", "keys": ["id"]}}}"#,
            r#"{"datasets": {"a/b": {"table": "t", "keys": ["id"]},
                              "a/c": {"table": "t", "keys": ["id"]}}}"#,
        ];
        for text in bad {
            assert!(Registry::from_json(text).is_err(), "{text}");
        }
    }

    #[test]
    fn rows_come_from_arrays_wrapped_records_and_single_objects() {
        let s = spec(&["id"]);
        let array = extract_rows(&s, &json!([{"id": 1}, {"id": 2}])).unwrap();
        assert_eq!(array.len(), 2);
        assert_eq!(array[0].keys, ["1"]);
        let wrapped = extract_rows(&s, &json!({"records": [{"id": "a"}]})).unwrap();
        assert_eq!(wrapped[0].keys, ["a"]);
        let single = extract_rows(&s, &json!({"id": 7, "name": "x"})).unwrap();
        assert_eq!(single.len(), 1);
        assert_eq!(single[0].payload["name"], "x");
        assert!(extract_rows(&s, &json!([])).unwrap().is_empty());
    }

    #[test]
    fn composite_keys_are_read_in_order() {
        let rows = extract_rows(&spec(&["b", "a"]), &json!([{"a": 1, "b": "x"}])).unwrap();
        assert_eq!(rows[0].keys, ["x", "1"]);
    }

    #[test]
    fn a_bad_record_rejects_the_whole_payload() {
        let s = spec(&["id"]);
        let cases = [
            (
                json!([{"id": 1}, {"name": "no key"}]),
                "missing or empty key",
            ),
            (json!([{"id": null}]), "missing or empty key"),
            (json!([{"id": "  "}]), "missing or empty key"),
            (json!([{"id": {"nested": 1}}]), "missing or empty key"),
            (json!([{"id": 1}, 5]), "not a JSON object"),
            (json!([{"id": 1}, {"id": 1}]), "duplicate key"),
            (json!("text"), "not a JSON array or object"),
        ];
        for (doc, expected) in cases {
            let err = extract_rows(&s, &doc).unwrap_err();
            assert!(err.contains(expected), "{err} should contain {expected}");
        }
    }

    #[test]
    fn hashes_and_batch_ids_are_deterministic() {
        let a = extract_rows(&spec(&["id"]), &json!([{"id": 1, "x": 2, "y": 3}])).unwrap();
        let b = extract_rows(&spec(&["id"]), &json!([{"y": 3, "x": 2, "id": 1}])).unwrap();
        assert_eq!(a[0].record_hash, b[0].record_hash);
        assert_eq!(a[0].record_hash.len(), 64);
        let id = batch_id(&"ab".repeat(32));
        assert_eq!(id, "abababab-abab-abab-abab-abababababab");
    }
}
