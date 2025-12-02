# alita

> [!WARNING]  
> The new (python) version of alita is written entirely by gpt-5.1-codex with little oversight (mostly basic code review and ensuring it works as expected).
> This is because I do not care about this and need it for other more interesting projects.
> Because of that, this code is generally pretty low quality and might have quirky silly stupid issues.
> Thankfully, I don't care. Good luck!

This works as a HTTP proxy server that requests a URL and, if the response is a challenge page, uses brave to pass it, then reuses the cookies for subsequent requests - essentially only using the browser when necessary to save resources.

This doesn't pass captchas, only the "please wait 5 seconds"-style challenge pages that solve with no user interaction, only JavaScript.
It could also be used to run javascript on pages.

## setup

```bash
$ docker run -p 4000:4000 sylver/alita
```

```yml
services:
    alita:
        container_name: alita
        image: sylver/alita
        restart: unless-stopped
        ports:
            - 4000:4000
```

### environment variables

| name                         | description                                                                                | default       |
| ---------------------------- | ------------------------------------------------------------------------------------------ | ------------- |
| `ALITA_HOST`                 | host/interface to bind                                                                     | `0.0.0.0`     |
| `ALITA_PORT`                 | port to bind                                                                               | `4000`        |
| `ALITA_DISABLE_SANDBOX`      | set to `true` to disable Chromium's sandbox (needed on some docker hosts)                  | `false`       |
| `ALITA_BROWSER_HEADLESS`     | run Brave headless when `true`; when `false`, Brave is fully rendered via Xvfb             | `false`       |
| `ALITA_XVFB_DISPLAY`         | display identifier to use when Xvfb is enabled                                             | `:99`         |
| `ALITA_XVFB_SCREEN`          | screen resolution/depth string passed to Xvfb                                              | `1600x900x24` |
| `ALITA_BROWSER_IDLE_SECONDS` | seconds before an idle browser (ie, no active tabs) is shut down                           | `10`          |
| `ALITA_READY_STATE_TIMEOUT`  | max seconds to wait for the document ready-state                                           | `20`          |
| `ALITA_READY_STATE_TARGET`   | ready-state to wait for before interacting with the page (`interactive`, `complete`, etc.) | `complete`    |
| `ALITA_HTTP_TIMEOUT`         | timeout (seconds) for plain HTTP requests                                                  | `20`          |

`ALITA_BROWSER_HEADLESS` defaults to false because for whatever reason, cloudflare challenges fail with headless browsers.

## usage

```ts
// "/get" expects a JSON body.
const response = await post("http://127.0.0.1:4000/get", {
    url: "https://example.com", // (required)
    // navigate with a browser if any of these selectors exist in the HTML response (optional)
    browser_on_elements: [
        ".block-page",
        ".captcha"
    ],
    // wait for this selector before assuming the block page is bypassed (required)
    wait_for_element: ".post-data",
    // maximum seconds to wait for the selector when the browser is used (optional)
    wait_timeout: 10,
})

// response is JSON with headers + body
// {
//     status_code: 200,
//     used_browser: false,
//     headers: {"content-type": "text/html; charset=utf-8", ...},
//     body: "<!doctype html>..."
// }
```
