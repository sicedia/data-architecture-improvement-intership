use chrono::Utc;
use hmac::{Hmac, Mac};
use log::{debug, error, info, warn};
use reqwest::Client;
use sha2::{Digest, Sha256};
use std::time::Duration;

type HmacSha256 = Hmac<Sha256>;

#[derive(Clone)]
pub struct RustFSS3Client {
    client: Client,
    endpoint: String,
    access_key: String,
    secret_key: String,
    region: String,
}

impl RustFSS3Client {
    pub fn new(endpoint: &str, access_key: &str, secret_key: &str) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .unwrap_or_else(|_| Client::new());

        let ep = endpoint.trim_end_matches('/').to_string();
        Self {
            client,
            endpoint: ep,
            access_key: access_key.to_string(),
            secret_key: secret_key.to_string(),
            region: "us-east-1".to_string(),
        }
    }

    fn hmac_sha256(key: &[u8], data: &[u8]) -> Vec<u8> {
        let mut mac = HmacSha256::new_from_slice(key).expect("HMAC can take key of any size");
        mac.update(data);
        mac.finalize().into_bytes().to_vec()
    }

    fn sha256_hex(data: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(data);
        hex::encode(hasher.finalize())
    }

    /// Asegura la existencia del bucket en RustFS S3, creándolo si no existe
    pub async fn ensure_bucket(&self, bucket: &str) -> Result<(), String> {
        let now = Utc::now();
        let amz_date = now.format("%Y%m%dT%H%M%SZ").to_string();
        let date_stamp = now.format("%Y%m%d").to_string();
        let url_path = format!("/{}", bucket);
        let full_url = format!("{}{}", self.endpoint, url_path);

        let parsed_endpoint = url::Url::parse(&self.endpoint)
            .map_err(|e| format!("Invalid S3 endpoint URL: {}", e))?;
        let host = parsed_endpoint.host_str().unwrap_or("rustfs").to_string();
        let host_header = if let Some(port) = parsed_endpoint.port() {
            format!("{}:{}", host, port)
        } else {
            host
        };

        let empty_payload_hash = Self::sha256_hex(b"");
        let canonical_headers = format!(
            "content-type:application/xml\nhost:{}\nx-amz-content-sha256:{}\nx-amz-date:{}\n",
            host_header, empty_payload_hash, amz_date
        );
        let signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date";
        let canonical_request = format!(
            "PUT\n{}\n\n{}\n{}\n{}",
            url_path, canonical_headers, signed_headers, empty_payload_hash
        );
        let canonical_request_hash = Self::sha256_hex(canonical_request.as_bytes());

        let credential_scope = format!("{}/{}/s3/aws4_request", date_stamp, self.region);
        let string_to_sign = format!(
            "AWS4-HMAC-SHA256\n{}\n{}\n{}",
            amz_date, credential_scope, canonical_request_hash
        );

        let k_secret = format!("AWS4{}", self.secret_key);
        let k_date = Self::hmac_sha256(k_secret.as_bytes(), date_stamp.as_bytes());
        let k_region = Self::hmac_sha256(&k_date, self.region.as_bytes());
        let k_service = Self::hmac_sha256(&k_region, b"s3");
        let k_signing = Self::hmac_sha256(&k_service, b"aws4_request");
        let signature = hex::encode(Self::hmac_sha256(&k_signing, string_to_sign.as_bytes()));

        let auth_header = format!(
            "AWS4-HMAC-SHA256 Credential={}/{}, SignedHeaders={}, Signature={}",
            self.access_key, credential_scope, signed_headers, signature
        );

        let _ = self
            .client
            .put(&full_url)
            .header("Host", &host_header)
            .header("Content-Type", "application/xml")
            .header("x-amz-date", &amz_date)
            .header("x-amz-content-sha256", &empty_payload_hash)
            .header("Authorization", &auth_header)
            .send()
            .await;

        Ok(())
    }

    /// Sube un objeto a RustFS S3 firmando con AWS SigV4
    pub async fn put_object(
        &self,
        bucket: &str,
        key: &str,
        body: &[u8],
        content_type: &str,
    ) -> Result<String, String> {
        let now = Utc::now();
        let amz_date = now.format("%Y%m%dT%H%M%SZ").to_string();
        let date_stamp = now.format("%Y%m%d").to_string();

        let clean_key = key.trim_start_matches('/');
        let url_path = format!("/{}/{}", bucket, clean_key);
        let full_url = format!("{}{}", self.endpoint, url_path);

        let parsed_endpoint = url::Url::parse(&self.endpoint)
            .map_err(|e| format!("Invalid S3 endpoint URL: {}", e))?;
        let host = parsed_endpoint
            .host_str()
            .unwrap_or("rustfs")
            .to_string();
        let host_header = if let Some(port) = parsed_endpoint.port() {
            format!("{}:{}", host, port)
        } else {
            host
        };

        let payload_hash = Self::sha256_hex(body);

        // Canonical Request
        let canonical_uri = url_path.clone();
        let canonical_query = "";
        let canonical_headers = format!(
            "content-type:{}\nhost:{}\nx-amz-content-sha256:{}\nx-amz-date:{}\n",
            content_type, host_header, payload_hash, amz_date
        );
        let signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date";

        let canonical_request = format!(
            "PUT\n{}\n{}\n{}\n{}\n{}",
            canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash
        );
        let canonical_request_hash = Self::sha256_hex(canonical_request.as_bytes());

        // String to Sign
        let credential_scope = format!("{}/{}/s3/aws4_request", date_stamp, self.region);
        let string_to_sign = format!(
            "AWS4-HMAC-SHA256\n{}\n{}\n{}",
            amz_date, credential_scope, canonical_request_hash
        );

        // Calculate Signature
        let k_secret = format!("AWS4{}", self.secret_key);
        let k_date = Self::hmac_sha256(k_secret.as_bytes(), date_stamp.as_bytes());
        let k_region = Self::hmac_sha256(&k_date, self.region.as_bytes());
        let k_service = Self::hmac_sha256(&k_region, b"s3");
        let k_signing = Self::hmac_sha256(&k_service, b"aws4_request");
        let signature = hex::encode(Self::hmac_sha256(&k_signing, string_to_sign.as_bytes()));

        let auth_header = format!(
            "AWS4-HMAC-SHA256 Credential={}/{}, SignedHeaders={}, Signature={}",
            self.access_key, credential_scope, signed_headers, signature
        );

        let resp_result = self
            .client
            .put(&full_url)
            .header("Host", &host_header)
            .header("Content-Type", content_type)
            .header("x-amz-date", &amz_date)
            .header("x-amz-content-sha256", &payload_hash)
            .header("Authorization", &auth_header)
            .body(body.to_vec())
            .send()
            .await;

        match resp_result {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    let s3_uri = format!("s3://{}/{}", bucket, clean_key);
                    debug!("[RustFS S3 PUT OK] {}", s3_uri);
                    Ok(s3_uri)
                } else {
                    let err = format!(
                        "Error HTTP {} subiendo objeto a RustFS S3 {}: {}",
                        status,
                        full_url,
                        resp.text().await.unwrap_or_default()
                    );
                    warn!("[RustFS S3 Error] {}", err);
                    Err(err)
                }
            }
            Err(e) => {
                let err = format!("Error de conexión con RustFS S3 ({}): {}", full_url, e);
                error!("[RustFS S3 Error] {}", err);
                Err(err)
            }
        }
    }
}
