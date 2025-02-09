// works around rust_analyzer not being able to resolve the protocol module
// this gives us intellisense for the protocol module
pub use headless_chrome::protocol;
