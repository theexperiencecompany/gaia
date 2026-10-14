"""HTTP header names and statuses the API sets by hand."""

#: Every surface that refuses a request with a retry hint — the rate limiter,
#: the request timeout, the paywall gate's 503 and the embedding sidecar —
#: spells this one name, so a client reading it can never miss one of them.
RETRY_AFTER_HEADER = "Retry-After"  # pragma: no mutate -- header names are case-insensitive (RFC 9110 section 5.1), so a case mutant is equivalent

#: nginx's "client closed request": the client hung up before the response, so nobody reads it.
CLIENT_CLOSED_REQUEST_STATUS = 499
