# RustWorker image. Build context: rust/source_runtime.
FROM rust:1 AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:stable-slim
COPY --from=build /src/target/release/source_runtime /usr/local/bin/source_runtime
EXPOSE 8088
USER nobody
ENTRYPOINT ["source_runtime", "serve"]
