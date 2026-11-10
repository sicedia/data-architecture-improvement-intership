//! `TextExtractor` over Apache Tika Server. Only the runtime calls it, only for complex binaries.

use std::time::Duration;

use crate::sinks::{SinkError, TextExtractor};

pub struct HttpTika {
    client: reqwest::Client,
    url: String,
}

impl HttpTika {
    pub fn new(base_url: &str) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(120))
            .build()
            .expect("reqwest client");
        Self {
            client,
            url: format!("{}/tika", base_url.trim_end_matches('/')),
        }
    }
}

impl TextExtractor for HttpTika {
    async fn extract_text(
        &self,
        data: &[u8],
        content_type: Option<&str>,
    ) -> Result<String, SinkError> {
        let mut req = self
            .client
            .put(&self.url)
            .header("Accept", "text/plain")
            .body(data.to_vec());
        if let Some(ct) = content_type {
            req = req.header("Content-Type", ct);
        }
        let resp = req
            .send()
            .await
            .map_err(|e| SinkError(format!("tika request: {e}")))?;
        let status = resp.status();
        if !status.is_success() {
            return Err(SinkError(format!("tika answered {status}")));
        }
        resp.text()
            .await
            .map_err(|e| SinkError(format!("tika body: {e}")))
    }
}
