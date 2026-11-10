//! `source_runtime serve`: the RustWorker HTTP service (configuration from the environment).
//! `source_runtime inspect <file> [content-type]`: prints the SHA-256, the detected kind and the
//! route of a file, without touching any storage.

use std::sync::Arc;

use source_runtime::bronze::Registry;
use source_runtime::config::Config;
use source_runtime::pg::PgBronze;
use source_runtime::runtime::SourceRuntime;
use source_runtime::s3::S3Landing;
use source_runtime::server::{router, AppState};
use source_runtime::tika::HttpTika;

use source_runtime::hashing::hash_bytes;
use source_runtime::triage::{classify, route, Hints, SNIFF_LEN};

async fn serve() -> Result<(), String> {
    let cfg = Config::from_env()?;
    let landing = S3Landing::new(
        &cfg.s3_endpoint,
        &cfg.s3_bucket,
        &cfg.s3_access_key,
        &cfg.s3_secret_key,
    );
    landing.ensure_bucket().await.map_err(|e| e.to_string())?;
    let bronze = PgBronze::connect(&cfg.database_url).map_err(|e| e.to_string())?;
    bronze.ping().await.map_err(|e| e.to_string())?;
    let registry = match &cfg.bronze_registry {
        Some(path) => Registry::from_file(std::path::Path::new(path))?,
        None => Registry::default(),
    };
    eprintln!("bronze registry: {} dataset(s)", registry.len());
    let state = Arc::new(AppState {
        runtime: SourceRuntime::new(landing, bronze, HttpTika::new(&cfg.tika_url))
            .with_registry(registry),
        max_body_bytes: cfg.max_body_bytes,
    });
    let listener = tokio::net::TcpListener::bind(&cfg.bind)
        .await
        .map_err(|e| format!("bind {}: {e}", cfg.bind))?;
    eprintln!("source_runtime listening on {}", cfg.bind);
    axum::serve(listener, router(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .map_err(|e| e.to_string())
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("serve") {
        if let Err(e) = serve().await {
            eprintln!("{e}");
            std::process::exit(1);
        }
        return;
    }
    inspect(&args);
}

fn inspect(args: &[String]) {
    if args.len() < 3 || args[1] != "inspect" {
        eprintln!("usage: source_runtime inspect <file> [content-type]");
        std::process::exit(2);
    }
    let bytes = match std::fs::read(&args[2]) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("cannot read {}: {e}", args[2]);
            std::process::exit(1);
        }
    };
    let hints = Hints {
        content_type: args.get(3).map(String::as_str),
        filename: Some(&args[2]),
    };
    let kind = classify(&bytes[..bytes.len().min(SNIFF_LEN)], &hints);
    println!("sha256={}", hash_bytes(&bytes));
    println!("size={}", bytes.len());
    println!("kind={kind:?}");
    println!("route={:?}", route(kind));
}
