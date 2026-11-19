"""HTTP header names, statuses and paths the API sets by hand."""

#: The prefix every client-facing route sits under: the one the deployed proxies forward. The
#: app mounts it as a literal, the only form tools/evlog_map resolves.
API_V1_PREFIX = "/api/v1"

#: Every surface that refuses a request with a retry hint — the rate limiter,
#: the request timeout, the paywall gate's 503 and the embedding sidecar —
#: spells this one name, so a client reading it can never miss one of them.
RETRY_AFTER_HEADER = "Retry-After"  # pragma: no mutate -- header names are case-insensitive (RFC 9110 section 5.1), so a case mutant is equivalent

#: nginx's "client closed request": the client hung up before the response, so nobody reads it.
CLIENT_CLOSED_REQUEST_STATUS = 499

#: Carries INTERNAL_API_TOKEN on the web app's server requests. Only rate limiting reads it.
INTERNAL_CALLER_HEADER = "X-Gaia-Internal"
#: The viewer a server request is made for, trusted only alongside a valid INTERNAL_CALLER_HEADER.
VIEWER_IP_HEADER = "X-Gaia-Viewer-IP"
#: The content-origin host a request arrived on, named by GAIA's usercontent Worker, which cannot
#: keep the browser's Host. Trusted only alongside a valid INTERNAL_CALLER_HEADER; a GAIA name, so
#: no proxy between the Worker and the API rewrites it the way they rewrite X-Forwarded-Host.
CONTENT_HOST_HEADER = "X-Gaia-Content-Host"
