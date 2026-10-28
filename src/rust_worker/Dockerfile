# ==============================================================================
# IDCI Rust Worker - Dockerfile Multi-Stage Build
# ==============================================================================
FROM rust:alpine AS builder

RUN apk add --no-cache musl-dev openssl-dev openssl-libs-static pkgconfig

WORKDIR /usr/src/app
COPY Cargo.toml ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src

COPY src ./src
RUN touch src/main.rs && cargo build --release

# Imagen final ultra-liviana de ejecución
FROM alpine:3.20

RUN apk add --no-cache ca-certificates libgcc curl

WORKDIR /app
COPY --from=builder /usr/src/app/target/release/idci_rust_worker /app/idci_rust_worker

ENV S3_ENDPOINT_URL="http://rustfs:9000" \
    S3_ACCESS_KEY="rustfsadmin" \
    S3_SECRET_KEY="rustfsadmin2026" \
    S3_BUCKET="opportunity-intelligence" \
    TIKA_URL="http://tika:9998" \
    RUST_LOG="info"

ENTRYPOINT ["/app/idci_rust_worker"]
CMD ["--input", "-"]
