# alita

This works as a HTTP proxy server that requests a URL and, if the response is a block page, uses chromium to run JavaScript and bypass the block page.
It will only use chromium if necessary, otherwise it uses a far cheaper `reqwest` request.
It avoids fetching the same URL twice by intercepting the document request and using the already fetched data.

This does NOT bypass CAPTCHAs, only the "please wait 5 seconds"-style pages that solve with no user interaction, only JavaScript.

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

| name                    | description                                                          | default                             |
| ----------------------- | -------------------------------------------------------------------- | ----------------------------------- |
| `ALITA_PORT`            | the port to listen on                                                | `4000`                              |
| `ALITA_HOST`            | the host to listen on                                                | `0.0.0.0`                           |
| `ALITA_TAB_POOL_SIZE`   | the maximum number of chromium tabs to open before queueing requests | `10`                                |
| `ALITA_DISABLE_SANDBOX` | whether to disable chromium sandboxing                               | `true` for docker otherwise `false` |
| `RUST_LOG`              | the log sources and level. `RUST_LOG=alita=debug` for debug logging  | `alita=info`                        |

## usage

```ts
// "get" can also be used, in which case these become query parameters, 
// with arrays as multiple values (ex, ?is_blocked_element=a&is_blocked_element=b)
const response = await post("http://127.0.0.1:4000", {
    url: "https://example.com",
    // these selectors decide if a page is a block page or not.
    // if a requested page contains any of these elements, the page is loaded into chromium
    // to let JavaScript bypass the block page.
    // if it does not, the page is returned as is.
    is_block_element: [
        '.block-page',
        '.captcha'
    ],
    // when a page is loaded into chromium, it waits for this element to appear before assuming the
    // block page is bypassed.
    wait_for_element: ".post-data",
    wait_timeout: 10, // this is the maximum time to wait for the element to appear
})

// response text is the HTML of the page.
// headers are not included in the response (yet).
```