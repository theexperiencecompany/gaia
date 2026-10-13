/** The schema's own path prefix; every generated `paths` key carries it. */
const SCHEMA_PREFIX = "/api/v1";

/**
 * The server root the generated `paths` hang off, from a configured base URL.
 *
 * Schema paths carry their own `/api/v1`, and routes like `/health` sit
 * outside it, so a typed client joins them to the origin, not the base.
 */
export function toApiOrigin(baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  return base.endsWith(SCHEMA_PREFIX)
    ? base.slice(0, -SCHEMA_PREFIX.length)
    : base;
}
