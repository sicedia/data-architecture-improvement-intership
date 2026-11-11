# Obscura TLS trust extras

Obscura `0.2.6` has **no flag** to ignore HTTPS certificate errors: its HTTP client is built with
`danger_accept_invalid_certs(false)`. Playwright's `ignore_https_errors=True` only affects a local
Chromium context; over CDP the TLS handshake is Obscura's.

Supported fix (official): add the missing CA(s) via `SSL_CERT_FILE` / `SSL_CERT_DIR`.

`certs/extra/` holds the Sectigo intermediates/roots that `www.caf.com` does not send in its chain
(see `ingestions/caf/discovery.md`). `docker-compose.yml` mounts that directory as
`SSL_CERT_DIR=/etc/obscura/extra-cas` and keeps the image's default `SSL_CERT_FILE`.
