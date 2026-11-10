//! Streaming SHA-256: payloads are hashed as they arrive, never loaded twice.

use sha2::{Digest, Sha256};
use tokio::io::{AsyncRead, AsyncReadExt};

/// Incremental hasher that also counts bytes.
#[derive(Default)]
pub struct StreamHasher {
    inner: Sha256,
    size: u64,
}

impl StreamHasher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn update(&mut self, chunk: &[u8]) {
        self.inner.update(chunk);
        self.size += chunk.len() as u64;
    }

    /// Lowercase hex digest and total size in bytes.
    pub fn finalize(self) -> (String, u64) {
        (to_hex(&self.inner.finalize()), self.size)
    }
}

/// Hash everything an async reader yields.
pub async fn hash_reader<R: AsyncRead + Unpin>(mut reader: R) -> std::io::Result<(String, u64)> {
    let mut hasher = StreamHasher::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = reader.read(&mut buf).await?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finalize())
}

/// SHA-256 of an in-memory slice.
pub fn hash_bytes(data: &[u8]) -> String {
    let mut hasher = StreamHasher::new();
    hasher.update(data);
    hasher.finalize().0
}

fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const EMPTY: &str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    const ABC: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    #[test]
    fn known_vectors() {
        assert_eq!(hash_bytes(b""), EMPTY);
        assert_eq!(hash_bytes(b"abc"), ABC);
    }

    #[test]
    fn chunking_does_not_change_the_digest() {
        let mut hasher = StreamHasher::new();
        hasher.update(b"a");
        hasher.update(b"bc");
        assert_eq!(hasher.finalize(), (ABC.to_string(), 3));
    }

    #[tokio::test]
    async fn hashes_an_async_reader() {
        let data: &[u8] = b"abc";
        assert_eq!(hash_reader(data).await.unwrap(), (ABC.to_string(), 3));
    }
}
