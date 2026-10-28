use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Metadatos y contenido de un archivo binario adjunto (PDF, Word, Excel, etc.)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BinaryFileItem {
    pub file_name: String,
    #[serde(default = "default_bin_ext")]
    pub file_extension: String,
    #[serde(default = "default_content_type")]
    pub content_type: String,
    #[serde(default)]
    pub file_size_bytes: usize,
    #[serde(default)]
    pub sha256_hash: String,
    #[serde(default)]
    pub source_url: String,
    #[serde(default)]
    pub local_path: Option<String>,
    #[serde(default)]
    pub raw_bytes_base64: Option<String>,
    #[serde(default)]
    pub document_type: Option<String>,
    #[serde(default)]
    pub scope: Option<String>,
    #[serde(default)]
    pub s3_uri: Option<String>,
    #[serde(default)]
    pub extracted_text: Option<String>,
    #[serde(default)]
    pub extracted_by_tika: Option<bool>,
}

fn default_bin_ext() -> String {
    ".bin".to_string()
}

fn default_content_type() -> String {
    "application/octet-stream".to_string()
}

/// Registro crudo emitido por el scraper (Scrapy / Playwright)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawScrapedRecord {
    pub call_code: String,
    #[serde(default)]
    pub page_code: Option<String>,
    #[serde(default)]
    pub opportunity_id: Option<String>,
    #[serde(default)]
    pub institution_name: Option<String>,
    #[serde(default = "default_source_system")]
    pub source_system: String,
    pub url: String,
    #[serde(default)]
    pub official_url: Option<String>,
    #[serde(default)]
    pub domain: Option<String>,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default = "default_actionability")]
    pub actionability_status: String,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub modality: Option<String>,
    #[serde(default)]
    pub call_for: Option<String>,
    #[serde(default)]
    pub program: Option<String>,
    #[serde(default)]
    pub programs: Option<Vec<String>>,
    #[serde(default)]
    pub is_cofinanced: Option<bool>,
    #[serde(default)]
    pub funded_by: Option<String>,
    #[serde(default)]
    pub funders: Option<Vec<String>>,
    #[serde(default)]
    pub issuing_entity: Option<String>,
    #[serde(default)]
    pub point_of_contact: Option<String>,
    #[serde(default)]
    pub deadline_raw: Option<String>,
    #[serde(default)]
    pub deadline_iso: Option<String>,
    #[serde(default)]
    pub clarifications_deadline: Option<String>,
    #[serde(default)]
    pub milestones: Option<Vec<serde_json::Value>>,
    #[serde(default)]
    pub budget_raw: Option<String>,
    #[serde(default = "default_currency")]
    pub currency: String,
    #[serde(default)]
    pub total_budget: Option<f64>,
    #[serde(default)]
    pub minimum_award: Option<f64>,
    #[serde(default)]
    pub maximum_award: Option<f64>,
    #[serde(default)]
    pub funding_rate: Option<String>,
    #[serde(default)]
    pub cost_sharing_required: Option<bool>,
    #[serde(default)]
    pub financial_conditions_summary: Option<String>,
    #[serde(default)]
    pub duration_raw: Option<String>,
    #[serde(default = "default_consortium")]
    pub consortium_mode: String,
    #[serde(default)]
    pub eligible_applicant_types: Option<Vec<String>>,
    #[serde(default)]
    pub geographic_scope: Option<String>,
    #[serde(default)]
    pub eligible_countries: Option<Vec<String>>,
    #[serde(default)]
    pub ecuador_eligible: Option<bool>,
    #[serde(default)]
    pub eligibility_text: Option<String>,
    #[serde(default)]
    pub eligibility_criteria: Option<Vec<String>>,
    #[serde(default)]
    pub mandatory_requirements: Option<Vec<String>>,
    #[serde(default)]
    pub evaluation_criteria: Option<Vec<String>>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default)]
    pub text_snippet: Option<String>,
    #[serde(default)]
    pub raw_html: Option<String>,
    #[serde(default)]
    pub downloaded_binaries: Option<Vec<BinaryFileItem>>,
    #[serde(default)]
    pub binary_files: Option<Vec<String>>,
    #[serde(default)]
    pub topics: Option<String>,
    #[serde(default)]
    pub scope: Option<String>,
    #[serde(default)]
    pub evidence_sources: Option<HashMap<String, String>>,
}

fn default_source_system() -> String {
    "idrc".to_string()
}
fn default_actionability() -> String {
    "actionable_opportunity".to_string()
}
fn default_status() -> String {
    "OPEN".to_string()
}
fn default_currency() -> String {
    "CAD".to_string()
}
fn default_consortium() -> String {
    "unknown".to_string()
}

/// Envoltorio de entrada que soporta recibir un array de registros o un objeto con campo "records"
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchInputEnvelope {
    #[serde(default)]
    pub batch_id: Option<String>,
    #[serde(default)]
    pub institution_name: Option<String>,
    #[serde(default)]
    pub source_system: Option<String>,
    #[serde(default)]
    pub spider: Option<String>,
    #[serde(default)]
    pub target_table: Option<String>,
    #[serde(default)]
    pub records: Vec<RawScrapedRecord>,
}

/// Manifest final persistido en RustFS S3 para el Loader
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinalBatchManifest {
    pub spider: String,
    pub institution_name: String,
    pub data_product: String,
    pub source_system: String,
    pub entity_name: String,
    pub target_table: String,
    pub code_field: String,
    pub batch_id: String,
    pub date_partition: String,
    pub batch_uri: String,
    pub extracted_at: String,
    pub processed_at: String,
    pub total_records: usize,
    pub complex_documents_processed_by_tika: usize,
    pub landing_uris: HashMap<String, String>,
    pub records: Vec<serde_json::Value>,
}
