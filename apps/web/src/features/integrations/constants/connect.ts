/**
 * After an OAuth connect the backend finishes the heavy MCP work (handshake +
 * tools/list + indexing) in the background, so the integration's tools land a
 * few seconds after the redirect. The integrations page polls until they
 * appear instead of forcing the user to reload the page.
 */
export const POST_CONNECT_POLL_INTERVAL_MS = 2000;
export const POST_CONNECT_POLL_MAX_ATTEMPTS = 15;

/**
 * CLI-transport connects are a state machine the backend advances one step per
 * POST, so the client re-POSTs until the status leaves `pending`. 2.5s keeps
 * the install/approval copy fresh without hammering the endpoint.
 */
export const CLI_CONNECT_POLL_INTERVAL_MS = 2500;
/**
 * Ceiling on how long the CLI connect dialog will keep polling. The server is
 * idempotent and will happily restart an expired device login forever, so
 * without a cap a user who opens the dialog and walks away drives an endless
 * loop — and every tick runs a verify command in a sandbox whose commands are
 * serialised per user, starving their other tool calls for as long as the tab
 * is open. 240 ticks x 2.5s = 10 minutes, matching the device-code window the
 * API allows (LOGIN_TIMEOUT_SECONDS).
 */
export const CLI_CONNECT_POLL_MAX_ATTEMPTS = 240;
