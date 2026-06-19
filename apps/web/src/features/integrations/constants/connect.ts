/**
 * After an OAuth connect the backend finishes the heavy MCP work (handshake +
 * tools/list + indexing) in the background, so the integration's tools land a
 * few seconds after the redirect. The integrations page polls until they
 * appear instead of forcing the user to reload the page.
 */
export const POST_CONNECT_POLL_INTERVAL_MS = 2000;
export const POST_CONNECT_POLL_MAX_ATTEMPTS = 15;
