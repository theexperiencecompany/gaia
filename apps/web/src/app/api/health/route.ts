import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const HEALTH_TIMEOUT_MS = 5000;

/**
 * Reverse-proxy health probe.
 *
 * Caddy/Nginx can poll `GET /api/health` (no auth, 5s timeout):
 * - API unreachable            → 503 {status:"api_down"}
 * - API healthy + needs_setup   → 503 {status:"setup_required"}
 * - API healthy + ready         → 200 {status:"ok"}
 *
 * The check hits the internal API's `GET /health` (or `/api/v1/health` via
 * the base URL) and then `GET /setup/status` to decide readiness.
 * Uses the server-side API base so the probe never leaves the compose network
 * when `API_BASE_URL_INTERNAL` is set; falls back to the public base for
 * single-container or dev runs.
 */
export async function GET() {
  const apiBase =
    process.env.API_BASE_URL_INTERNAL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000/api/v1";

  const buildUrl = (path: string) => {
    const url = new URL(apiBase);
    url.pathname = `${url.pathname.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
    return url.toString();
  };

  const healthUrl = buildUrl("health");
  const setupStatusUrl = buildUrl("setup/status");

  // 1) Is the API itself reachable?
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const res = await fetch(healthUrl, {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`health returned ${res.status}`);
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ status: "api_down" }, { status: 503 });
  }

  // 2) API is up — is setup complete?
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const res = await fetch(setupStatusUrl, {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!res.ok) {
        return NextResponse.json({ status: "api_down" }, { status: 503 });
      }
      const data = (await res.json()) as { needs_setup?: boolean };
      if (data.needs_setup) {
        return NextResponse.json({ status: "setup_required" }, { status: 503 });
      }
      return NextResponse.json({ status: "ok" }, { status: 200 });
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ status: "api_down" }, { status: 503 });
  }
}
