//! `LandingSink` over any S3 API (RustFS). Objects are immutable and content-addressed.

use aws_sdk_s3::config::{
    BehaviorVersion, Credentials, Region, RequestChecksumCalculation, ResponseChecksumValidation,
};
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client;

use crate::sinks::{LandingSink, SinkError};

pub struct S3Landing {
    client: Client,
    bucket: String,
}

impl S3Landing {
    pub fn new(endpoint: &str, bucket: &str, access_key: &str, secret_key: &str) -> Self {
        let config = aws_sdk_s3::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .endpoint_url(endpoint)
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::new(access_key, secret_key, None, None, "env"))
            .force_path_style(true)
            // S3-compatible servers do not always accept the default trailing checksums.
            .request_checksum_calculation(RequestChecksumCalculation::WhenRequired)
            .response_checksum_validation(ResponseChecksumValidation::WhenRequired)
            .build();
        Self {
            client: Client::from_conf(config),
            bucket: bucket.to_string(),
        }
    }

    /// Create the Landing bucket when it does not exist yet.
    pub async fn ensure_bucket(&self) -> Result<(), SinkError> {
        if self
            .client
            .head_bucket()
            .bucket(&self.bucket)
            .send()
            .await
            .is_ok()
        {
            return Ok(());
        }
        self.client
            .create_bucket()
            .bucket(&self.bucket)
            .send()
            .await
            .map_err(|e| SinkError(format!("create bucket {}: {e:?}", self.bucket)))?;
        Ok(())
    }
}

impl LandingSink for S3Landing {
    async fn put(&self, key: &str, data: &[u8]) -> Result<(), SinkError> {
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(data.to_vec()))
            .send()
            .await
            .map_err(|e| SinkError(format!("put {key}: {e:?}")))?;
        Ok(())
    }

    fn uri(&self, key: &str) -> String {
        format!("s3://{}/{key}", self.bucket)
    }
}
