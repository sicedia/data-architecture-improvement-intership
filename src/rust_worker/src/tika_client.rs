use log::{debug, error, info, warn};
use reqwest::Client;
use std::time::Duration;

pub struct TikaClient {
    client: Client,
    tika_url: String,
}

impl TikaClient {
    pub fn new(tika_url: &str) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .unwrap_or_else(|_| Client::new());

        let url = tika_url.trim_end_matches('/').to_string();
        Self {
            client,
            tika_url: url,
        }
    }

    /// Determina si un archivo califica como documento complejo que debe ser enviado a Apache Tika
    pub fn is_complex_document(ext: &str) -> bool {
        let clean = ext.trim().to_lowercase();
        matches!(
            clean.as_str(),
            ".pdf" | "pdf" |
            ".docx" | "docx" |
            ".doc" | "doc" |
            ".xlsx" | "xlsx" |
            ".xls" | "xls" |
            ".pptx" | "pptx" |
            ".ppt" | "ppt" |
            ".odt" | "odt" |
            ".rtf" | "rtf" |
            ".zip" | "zip"
        )
    }

    /// Envía el archivo binario a Apache Tika (`PUT /tika`) para extraer texto estructurado
    pub async fn extract_text(
        &self,
        bytes: &[u8],
        file_name: &str,
        content_type: &str,
    ) -> Result<String, String> {
        let endpoint = format!("{}/tika", self.tika_url);
        info!(
            "[Rust -> Tika] Despachando documento complejo: '{}' ({} bytes | {}) hacia {}",
            file_name,
            bytes.len(),
            content_type,
            endpoint
        );

        let resp_result = self
            .client
            .put(&endpoint)
            .header("Content-Type", content_type)
            .header("Accept", "text/plain; charset=utf-8")
            .body(bytes.to_vec())
            .send()
            .await;

        match resp_result {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    let raw_text = resp
                        .text()
                        .await
                        .unwrap_or_default();
                    // Sanitizar caracteres nulos incompatibles con PostgreSQL
                    let sanitized = raw_text.replace('\x00', "").replace("\u{0000}", "");
                    let words_count = sanitized.split_whitespace().count();
                    info!(
                        "[Tika -> Rust] Extracción exitosa para '{}': {} caracteres (aprox. {} palabras).",
                        file_name,
                        sanitized.len(),
                        words_count
                    );
                    Ok(sanitized)
                } else {
                    let err_msg = format!(
                        "Apache Tika respondió con código HTTP {}: {}",
                        status,
                        resp.text().await.unwrap_or_default()
                    );
                    warn!("[Tika Warning] {}", err_msg);
                    Err(err_msg)
                }
            }
            Err(e) => {
                let err_msg = format!("Fallo al conectar con Apache Tika en {}: {}", endpoint, e);
                warn!("[Tika Fallback] {}. Se continuará sin texto de Tika.", err_msg);
                Err(err_msg)
            }
        }
    }
}
