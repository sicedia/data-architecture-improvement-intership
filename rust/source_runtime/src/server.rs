//! HTTP transport between Python extractors and the runtime.
//!
//! `POST /v1/ingest/{source}/{dataset}` with the payload as the request body (chunked transfer is
//! accepted) and the headers `X-Ingest-Date` (YYYY-MM-DD, chosen by the caller so the runtime stays
//! deterministic), `Content-Type` and `X-Filename` as optional triage hints. The answer is the
//! JSON receipt. `GET /healthz` reports liveness.

use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::json;

use crate::runtime::{Payload, SourceRuntime};
use crate::sinks::{BronzeSink, LandingSink, TextExtractor};
use crate::triage::{Hints, Route};

pub struct AppState<L, B, T> {
    pub runtime: SourceRuntime<L, B, T>,
    pub max_body_bytes: usize,
}

fn fail(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({ "error": message.into() }))).into_response()
}

/// Keys are built from these values, so only a conservative alphabet is accepted.
pub fn valid_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}

pub fn valid_date(value: &str) -> bool {
    let b = value.as_bytes();
    b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b.iter()
            .enumerate()
            .all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit())
}

fn route_name(route: Route) -> &'static str {
    match route {
        Route::Bronze => "bronze",
        Route::Tika => "tika",
        Route::Quarantine => "quarantine",
    }
}

async fn ingest<L, B, T>(
    State(state): State<Arc<AppState<L, B, T>>>,
    Path((source, dataset)): Path<(String, String)>,
    headers: HeaderMap,
    body: Body,
) -> Response
where
    L: LandingSink + Send + Sync + 'static,
    B: BronzeSink + Send + Sync + 'static,
    T: TextExtractor + Send + Sync + 'static,
{
    if !valid_name(&source) || !valid_name(&dataset) {
        return fail(
            StatusCode::BAD_REQUEST,
            "source and dataset must match [a-z0-9_-]{1,64}",
        );
    }
    let header = |name: &str| headers.get(name).and_then(|v| v.to_str().ok());
    let Some(ingest_date) = header("x-ingest-date").filter(|d| valid_date(d)) else {
        return fail(
            StatusCode::BAD_REQUEST,
            "X-Ingest-Date (YYYY-MM-DD) is required",
        );
    };
    let bytes = match to_bytes(body, state.max_body_bytes).await {
        Ok(b) => b,
        Err(_) => {
            return fail(
                StatusCode::PAYLOAD_TOO_LARGE,
                "payload too large or truncated",
            )
        }
    };
    let payload = Payload {
        source: &source,
        dataset: &dataset,
        ingest_date,
        bytes: &bytes,
        hints: Hints {
            content_type: header("content-type"),
            filename: header("x-filename"),
        },
    };
    match state.runtime.process(&payload).await {
        Ok(out) => Json(json!({
            "source_id": source,
            "dataset": dataset,
            "sha256": out.sha256,
            "size_bytes": out.size,
            "object_key": out.landing_key,
            "route": route_name(out.route),
            "text_key": out.text_key,
            "bronze_table": out.bronze_load.as_ref().map(|l| l.table.clone()),
            "bronze_rows": out.bronze_load.as_ref().map(|l| l.rows),
        }))
        .into_response(),
        Err(e) => fail(StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

pub fn router<L, B, T>(state: Arc<AppState<L, B, T>>) -> Router
where
    L: LandingSink + Send + Sync + 'static,
    B: BronzeSink + Send + Sync + 'static,
    T: TextExtractor + Send + Sync + 'static,
{
    Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/v1/ingest/{source}/{dataset}", post(ingest::<L, B, T>))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bronze::Registry;
    use crate::sinks::memory::{CountingTika, MemoryBronze, MemoryLanding};
    use axum::http::Request;
    use tower::ServiceExt;

    fn app() -> (
        Router,
        Arc<AppState<MemoryLanding, MemoryBronze, CountingTika>>,
    ) {
        let state = Arc::new(AppState {
            runtime: SourceRuntime::new(Default::default(), Default::default(), Default::default())
                .with_registry(
                    Registry::from_json(
                        r#"{"datasets": {"demo/records":
                            {"table": "demo__records", "keys": ["id"]}}}"#,
                    )
                    .unwrap(),
                ),
            max_body_bytes: 1024,
        });
        (router(state.clone()), state)
    }

    async fn call(app: Router, req: Request<Body>) -> (StatusCode, serde_json::Value) {
        let resp = app.oneshot(req).await.unwrap();
        let status = resp.status();
        let bytes = to_bytes(resp.into_body(), usize::MAX).await.unwrap();
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(json!(null)),
        )
    }

    fn post_req(uri: &str, date: Option<&str>, body: &'static [u8]) -> Request<Body> {
        let mut b = Request::post(uri);
        if let Some(d) = date {
            b = b.header("x-ingest-date", d);
        }
        b.body(Body::from(body)).unwrap()
    }

    #[tokio::test]
    async fn json_ingest_returns_a_receipt_and_loads_the_typed_table() {
        let (app, state) = app();
        let (status, v) = call(
            app,
            post_req(
                "/v1/ingest/demo/records",
                Some("2026-11-09"),
                b"[{\"id\":1}]",
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["route"], "bronze");
        assert_eq!(v["size_bytes"], 10);
        assert_eq!(v["bronze_table"], "demo__records");
        assert_eq!(v["bronze_rows"], 1);
        assert_eq!(
            state.runtime.bronze.rows.lock().unwrap()["demo__records"].len(),
            1
        );
        assert_eq!(*state.runtime.tika.calls.lock().unwrap(), 0);
    }

    #[tokio::test]
    async fn pdf_ingest_goes_through_tika() {
        let (app, state) = app();
        let (status, v) = call(
            app,
            post_req("/v1/ingest/demo/docs", Some("2026-11-09"), b"%PDF-1.7 x"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["route"], "tika");
        assert!(v["text_key"].as_str().unwrap().ends_with(".txt"));
        assert_eq!(*state.runtime.tika.calls.lock().unwrap(), 1);
    }

    #[tokio::test]
    async fn bad_names_and_missing_date_are_rejected() {
        let (app, _) = app();
        let (s, _) = call(
            app.clone(),
            post_req("/v1/ingest/De..mo/records", Some("2026-11-09"), b"{}"),
        )
        .await;
        assert_eq!(s, StatusCode::BAD_REQUEST);
        let (s, _) = call(
            app.clone(),
            post_req("/v1/ingest/demo/records", None, b"{}"),
        )
        .await;
        assert_eq!(s, StatusCode::BAD_REQUEST);
        let (s, _) = call(
            app,
            post_req("/v1/ingest/demo/records", Some("09-11-2026"), b"{}"),
        )
        .await;
        assert_eq!(s, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn oversized_payload_is_rejected() {
        let (app, state) = app();
        let big: &'static [u8] = Box::leak(vec![b'a'; 2048].into_boxed_slice());
        let (s, _) = call(
            app,
            post_req("/v1/ingest/demo/records", Some("2026-11-09"), big),
        )
        .await;
        assert_eq!(s, StatusCode::PAYLOAD_TOO_LARGE);
        assert!(state.runtime.bronze.rows.lock().unwrap().is_empty());
    }
}
