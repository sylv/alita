FROM clux/muslrust:stable AS planner
RUN cargo install cargo-chef
COPY . .
RUN cargo chef prepare --recipe-path recipe.json


FROM clux/muslrust:stable AS cacher
RUN cargo install cargo-chef
COPY --from=planner /volume/recipe.json recipe.json
RUN cargo chef cook --release --target x86_64-unknown-linux-musl --recipe-path recipe.json


FROM clux/muslrust:stable AS builder
COPY . .
COPY --from=cacher /volume/target target
COPY --from=cacher /root/.cargo /root/.cargo
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    cargo build --bin alita --release --target x86_64-unknown-linux-musl
RUN strip target/x86_64-unknown-linux-musl/release/alita


FROM alpine:latest AS runtime
RUN apk add --no-cache chromium
RUN addgroup -S nonroot && adduser -S nonroot -G nonroot
COPY --from=builder --chown=nonroot:nonroot /volume/target/x86_64-unknown-linux-musl/release/alita /app/alita
USER nonroot
# for some reason chrome doesn't work in sandbox mode. it just hangs at startup
# this works around that
ENV ALITA_DISABLE_SANDBOX=true
ENTRYPOINT ["/app/alita"]