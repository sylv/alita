use alita::request::FetchRequest;
use axum::extract::State;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use axum_extra::extract::Query;
use error::AppError;
use fetch::Fetch;
use std::env;
use std::error::Error;
use std::sync::Arc;
use tokio::signal;
use tower_http::compression::CompressionLayer;
use tracing::info;

mod error;
mod fetch;
mod protocol;
mod tab_manager;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    tracing_subscriber::fmt::init();
    dotenv::dotenv().ok();

    let fetch = Arc::new(Fetch::new());
    let compression_layer = CompressionLayer::new();
    let app = Router::new()
        .route("/", get(get_url))
        .route("/", post(post_url))
        .layer(compression_layer)
        .with_state(fetch);

    let bind_host = env::var("ALITA_HOST").unwrap_or("0.0.0.0".to_string());
    let bind_port = env::var("ALITA_PORT").unwrap_or("4000".to_string());
    let bind_addr = format!("{}:{}", bind_host, bind_port);
    let listener = tokio::net::TcpListener::bind(bind_addr).await.unwrap();
    info!("Listening on {}", listener.local_addr().unwrap());
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap();

    Ok(())
}

#[axum::debug_handler]
async fn get_url(
    State(fetch): State<Arc<Fetch>>,
    Query(query): Query<FetchRequest>,
) -> Result<impl IntoResponse, AppError> {
    let result = fetch.get_html(query).await?;
    Ok(result)
}

#[axum::debug_handler]
async fn post_url(
    State(fetch): State<Arc<Fetch>>,
    Json(body): Json<FetchRequest>,
) -> Result<impl IntoResponse, AppError> {
    let result = fetch.get_html(body).await?;
    Ok(result)
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("failed to install signal handler")
            .recv()
            .await;
    };

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
