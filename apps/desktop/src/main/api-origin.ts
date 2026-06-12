/**
 * API Origin Resolution
 *
 * The renderer learns the API origin from `NEXT_PUBLIC_API_BASE_URL` at
 * Next.js build time, but that variable is NOT present in the Electron
 * main process environment. Falling back to the production URL in dev
 * silently stored auth cookies on `api.heygaia.io` while the app talked
 * to `localhost:8000` — every authenticated request 401'd.
 *
 * @module api-origin
 */

import { isProductionServer } from "./server-config";

/** Local FastAPI dev server origin. */
const DEV_API_ORIGIN = "http://localhost:8000";

/** Production API origin. */
const PROD_API_ORIGIN = "https://api.heygaia.io";

/**
 * Resolve the API origin for the current environment.
 *
 * Honors `NEXT_PUBLIC_API_BASE_URL` when explicitly provided to the
 * main process; otherwise localhost in dev, production URL when packaged.
 */
export function getApiOrigin(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (fromEnv) return fromEnv.replace(/\/api\/v1\/?$/, "");

  return isProductionServer() ? PROD_API_ORIGIN : DEV_API_ORIGIN;
}

/** Whether the resolved API origin is served over HTTPS. */
export function isApiOriginSecure(): boolean {
  return getApiOrigin().startsWith("https://");
}
