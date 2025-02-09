use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct FetchRequest {
    pub url: String,
    pub wait_for_element: Option<String>,
    pub wait_timeout: Option<usize>,
    #[serde(default, rename = "is_block_element")]
    pub is_blocked_elements: Vec<String>,
}
