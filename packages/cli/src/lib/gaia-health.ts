/**
 * Whether GAIA — not merely something — answers at an API base. Every command
 * that asks "is GAIA up?" asks it here: the port can be held by another
 * program, and only the health body tells the two apart.
 * @module lib/gaia-health
 */

import { mediaType } from "@gaia/shared/api/apiError";
import type {
  DegradedHealthResponse,
  HealthResponse,
} from "@gaia/shared/api/generated";
import { fetchWithTimeout } from "./setup-endpoints.js";

/** Loopback answers in milliseconds; this only bounds a hung socket. */
const PROBE_TIMEOUT_MS = 2_000;

export type GaiaProbe =
  | { kind: "gaia"; degraded: boolean }
  | { kind: "unreachable" }
  | {
      kind: "other";
      status: number;
      contentType: string;
      /** Where a cross-origin redirect took the probe, when one did. */
      redirectedTo?: string;
    };

/**
 * Whether a body is GAIA's health answer. Both shapes carry the event-loop
 * lag; the online one adds a version, the degraded one a detail — fields no
 * unrelated server answers /ping with.
 */
function isGaiaHealth(
  body: unknown,
): body is HealthResponse | DegradedHealthResponse {
  if (typeof body !== "object" || body === null) return false;
  const answer = body as Record<string, unknown>;
  if (typeof answer["event_loop_lag_ms"] !== "number") return false;
  return (
    typeof answer["version"] === "string" ||
    typeof answer["detail"] === "string"
  );
}

/**
 * Probe an API base (`…/api/v1`). The body decides, not the status code:
 * `/ping` answers 503 with the same shape while the event loop is lagged, and
 * any other program answers 200/404 with its own body.
 */
export async function probeGaia(apiUrl: string): Promise<GaiaProbe> {
  const target = new URL(`${apiUrl}/ping`);
  let res: Response;
  try {
    res = await fetchWithTimeout(target.href, undefined, PROBE_TIMEOUT_MS);
  } catch {
    return { kind: "unreachable" };
  }

  // fetch follows redirects, and res.url is where the answer came from. A body
  // from another origin says nothing about the origin being probed, so it must
  // not count as evidence — and never silently becomes the pairing target.
  const answeredAt = res.url ? new URL(res.url) : target;
  if (answeredAt.origin !== target.origin) {
    return {
      kind: "other",
      status: res.status,
      contentType: mediaType(res),
      redirectedTo: answeredAt.href,
    };
  }

  const body: unknown = await res.json().catch(() => undefined);
  if (!isGaiaHealth(body)) {
    return { kind: "other", status: res.status, contentType: mediaType(res) };
  }
  return { kind: "gaia", degraded: body.status === "degraded" };
}
