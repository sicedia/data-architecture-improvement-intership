//! `source_runtime`: native SourceRuntime / RustWorker, placed in front of RustFS.
//!
//! Python extractors stream raw bytes here over HTTP. The runtime computes SHA-256, triages the
//! payload and loads it: complex binaries (PDF, DOCX) pass through Tika before loading, everything
//! else is loaded directly. No LLM or non-deterministic logic belongs in this crate (invariant 1).

pub mod bronze;
pub mod config;
pub mod hashing;
pub mod pg;
pub mod runtime;
pub mod s3;
pub mod server;
pub mod sinks;
pub mod tika;
pub mod triage;
