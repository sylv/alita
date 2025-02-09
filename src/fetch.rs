use std::collections::HashMap;
use std::env::{self, temp_dir};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use crate::protocol::protocol::cdp::Fetch::events::RequestPausedEvent;
use crate::protocol::protocol::cdp::Fetch::FailRequest;
use crate::protocol::protocol::cdp::Network::ErrorReason;
use crate::protocol::protocol::cdp::Network::ResourceType;
use crate::tab_manager::TabManager;
use alita::request::FetchRequest;
use anyhow::Result;
use base64::Engine;
use deadpool::managed::Pool;
use headless_chrome::browser::tab::RequestPausedDecision;
use headless_chrome::browser::transport::{SessionId, Transport};
use headless_chrome::protocol::cdp::Fetch::{FulfillRequest, HeaderEntry};
use headless_chrome::Tab;
use headless_chrome::{Browser, LaunchOptionsBuilder};
use lazy_static::lazy_static;
use reqwest::Client;
use scraper::Html;
use tracing::{debug, info};

lazy_static! {
    // todo: we should get these from the browser so it doesn't go out of sync,
    // but this is fine for now.
    pub static ref HEADERS: HashMap<String, String> = {
        vec![
            ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
            ("Accept-Language", "en-US,en;q=0.9"),
            ("Priority", "u=0, i"),
            ("Sec-Fetch-Dest", "document"),
            ("Sec-Fetch-Mode", "navigate"),
            ("Sec-Fetch-Site", "none"),
            ("Sec-Fetch-User", "?1"),
            ("Upgrade-Insecure-Requests", "1"),
            ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
    };
}

pub struct Fetch {
    client: Client,
    tabs: Pool<TabManager>,
}

impl Fetch {
    pub fn new() -> Self {
        let user_data_dir = temp_dir().join("alita-profile");
        debug!("Using user data dir: {:?}", user_data_dir);
        let sandbox = env::var("ALITA_DISABLE_SANDBOX").is_err();
        let browser = Browser::new(
            LaunchOptionsBuilder::default()
                .headless(true)
                .sandbox(sandbox)
                .idle_browser_timeout(Duration::from_secs(31560000))
                .user_data_dir(Some(user_data_dir.into()))
                .build()
                .unwrap(),
        )
        .unwrap();

        let headers = HEADERS.clone();
        let headers = (&headers).try_into().expect("Failed to convert headers");
        let client = Client::builder().default_headers(headers).build().unwrap();

        let browser = Arc::new(browser);
        let max_size = env::var("ALITA_TAB_POOL_SIZE")
            .unwrap_or("10".to_string())
            .parse::<usize>()
            .expect("Failed to parse ALITA_TAB_POOL_SIZE");

        let tabs = Pool::builder(TabManager { browser })
            .max_size(max_size)
            .build()
            .unwrap();

        Fetch { tabs, client }
    }

    pub async fn get_html(&self, req: FetchRequest) -> Result<String> {
        info!("Fetching {:?}", &req);
        let html = {
            debug!("Fetching html from {} with reqwest", &req.url);
            let res = self.client.get(&req.url).send().await?.error_for_status()?;
            let html = res.text().await?;

            // if the html contains any elements matching is_blocked_elements, we hit a block page and have to
            // retry with chrome.
            let document = scraper::Html::parse_document(&html);
            let is_blocked = self.is_blocked(&document, &req.is_blocked_elements);

            // we can't cross .await boundaries with Html, so
            // this is the least ugly way to reuse the parsed doc
            if is_blocked {
                // reuse the html we fetched with chrome
                Some(html)
            } else {
                return Ok(html);
            }
        };

        debug!("Found blocked element, retrying with chrome");
        self.fetch_with_chrome(req, html).await
    }

    async fn fetch_with_chrome(&self, req: FetchRequest, html: Option<String>) -> Result<String> {
        debug!("Fetching html from {} with chrome", &req.url);
        let tab = self.tabs.get().await.expect("Failed to get tab");
        self.configure_interceptor(&tab, html)?;
        tab.navigate_to(&req.url)?;
        if let Some(wait_for_element) = &req.wait_for_element {
            let wait_timeout = req.wait_timeout.unwrap_or(20);
            let wait_timeout = Duration::from_secs(wait_timeout as u64);
            tab.wait_for_element_with_custom_timeout(&wait_for_element, wait_timeout)?;
        } else {
            tab.wait_until_navigated()?;
        }

        let html = tab.get_content()?;

        // the tab sits idle in the background. we "park" it on a blank page
        // so that javascript/tracking/etc doesnt run in the background for no reason.
        tab.navigate_to("about:blank")?;

        let document = scraper::Html::parse_document(&html);
        let is_blocked = self.is_blocked(&document, &req.is_blocked_elements);
        if is_blocked {
            Err(anyhow::anyhow!(
                "Used chrome to bypass pages but blocked elements are still present"
            ))
        } else {
            Ok(html)
        }
    }

    fn configure_interceptor(&self, tab: &Arc<Tab>, html: Option<String>) -> Result<()> {
        // this configures the interception handler
        let used_html = AtomicBool::new(false);
        let html = Arc::new(html);
        tab.enable_request_interception(Arc::new(
            move |_t: Arc<Transport>, _sid: SessionId, intercepted: RequestPausedEvent| {
                let is_ico = intercepted.params.request.url.ends_with(".ico");
                if is_ico {
                    return RequestPausedDecision::Continue(None);
                }

                match intercepted.params.resource_Type {
                    ResourceType::Image
                    | ResourceType::Stylesheet
                    | ResourceType::Media
                    | ResourceType::Font
                    | ResourceType::Ping
                    | ResourceType::Manifest => RequestPausedDecision::Fail(FailRequest {
                        request_id: intercepted.params.request_id,
                        error_reason: ErrorReason::Aborted,
                    }),
                    ResourceType::Document => {
                        if let Some(html) = html.as_ref() {
                            if !used_html.load(Ordering::Relaxed) {
                                // if we have html, we reply to the request with it to save a request to the server
                                debug!("Fulfilling request with cached html");
                                let headers = vec![HeaderEntry {
                                    name: "Content-Type".to_string(),
                                    value: "text/html".to_string(),
                                }];

                                used_html.store(true, Ordering::Relaxed);
                                return RequestPausedDecision::Fulfill(FulfillRequest {
                                    request_id: intercepted.params.request_id,
                                    response_code: 200,
                                    response_headers: Some(headers),
                                    body: Some(base64::prelude::BASE64_STANDARD.encode(&html)),
                                    binary_response_headers: None,
                                    response_phrase: None,
                                });
                            }
                        }

                        RequestPausedDecision::Continue(None)
                    }
                    _ => RequestPausedDecision::Continue(None),
                }
            },
        ))?;

        Ok(())
    }

    fn is_blocked(&self, document: &Html, selectors: &[String]) -> bool {
        for selector in selectors {
            if let Ok(selector) = scraper::Selector::parse(selector) {
                if document.select(&selector).next().is_some() {
                    return true;
                }
            }
        }

        false
    }
}
