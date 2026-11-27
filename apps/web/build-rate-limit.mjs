/**
 * How long a production build waits out the API's rate limit, and the page timeout that leaves room for it.
 * Plain-js on purpose: `next.config.mjs` (Node) imports it and cannot load TS.
 */

/** The API's app-wide ceilings are per minute, so a longer Retry-After is a limit a build cannot wait out. */
export const MAX_RATE_LIMIT_WAIT_SECONDS = 60;

/** 429 windows one build-time API read waits out before the build fails on it. */
export const BUILD_RATE_LIMIT_WAITS = 2;

/** API reads the slowest prerendered page (a marketplace detail) makes one after another. */
const SEQUENTIAL_READS_PER_PAGE = 4;

/** Render time a page gets on top of its waits: Next's own default page timeout. */
const RENDER_SECONDS = 60;

/** Next's per-page prerender timeout; at its 60s default one waited-out 429 timed the page out. */
export const STATIC_PAGE_GENERATION_TIMEOUT_SECONDS =
  SEQUENTIAL_READS_PER_PAGE *
    BUILD_RATE_LIMIT_WAITS *
    MAX_RATE_LIMIT_WAIT_SECONDS +
  RENDER_SECONDS;
