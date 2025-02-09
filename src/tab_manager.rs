use crate::fetch::HEADERS;
use crate::protocol::protocol::cdp::Fetch::{RequestPattern, RequestStage};
use anyhow::Result;
use deadpool::managed::{Manager, RecycleResult};
use headless_chrome::Browser;
use headless_chrome::Tab;
use std::sync::Arc;

pub struct TabManager {
    pub browser: Arc<Browser>,
}

// todo: this is kinda mid, a more appropriate pool would be better
impl Manager for TabManager {
    type Type = Arc<Tab>;
    type Error = anyhow::Error;

    async fn create(&self) -> Result<Self::Type, Self::Error> {
        let tab = self.browser.new_tab()?;

        tab.enable_stealth_mode()?;

        // stealth mode has a bug where it wraps the user agent in quotes
        // https://github.com/rust-headless-chrome/rust-headless-chrome/issues/531
        // this works around that by using our own user agent, and it ensures consistency with reqwest
        let user_agent = HEADERS
            .get("User-Agent")
            .expect("User-Agent header not found");
        tab.set_user_agent(&user_agent, None, None)?;

        // this tells chrome we want to intercept requests, it starts sending us requests
        tab.enable_fetch(
            Some(
                vec![RequestPattern {
                    url_pattern: None,
                    resource_Type: None,
                    request_stage: Some(RequestStage::Request),
                }]
                .as_slice(),
            ),
            None,
        )?;

        Ok(tab)
    }

    async fn recycle(
        &self,
        _tab: &mut Arc<Tab>,
        _metrics: &deadpool::managed::Metrics,
    ) -> RecycleResult<Self::Error> {
        Ok(())
    }
}
