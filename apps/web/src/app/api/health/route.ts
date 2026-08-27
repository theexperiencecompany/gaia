import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const HEALTH_TIMEOUT_MS = 5000;

/**
 * Reverse-proxy health probe.
 *
 * Caddy/Nginx can poll `GET /api/health` (no auth, 5s timeout):
 * - API unreachable            → 503 {status:"api_down"}
 * - API healthy + needs_setup   → 200 {status:"setup_required"} (liveness OK, wizard is expected)
 * - API healthy + ready         → 200 {status:"ok"}
 *
 * Health is liveness (is the process up?), setup is readiness (is first-run
 * complete?). Returning 503 for setup_required would keep `depends_on:
 * service_healthy` / LB checks unhealthy during the first-run wizard and
 * trigger restarts mid-setup — so only api_down is 503.
 *
 * The check hits the internal API's `GET /health` (or `/api/v1/health` via
 * the base URL) and then `GET /setup/status` to decide readiness.
 * Uses the server-side API base so the probe never leaves the compose network
 * when `API_BASE_URL_INTERNAL` is set; falls back to the public base for
 * single-container or dev runs.
 *
 * Infra coverage (postgres/redis/mongo/rabbitmq/chroma):
 * - The web container has no DB clients, so it delegates infra health to the
 *   API. The API's `GET /health` returns 503 on event-loop lag and the
 *   self-host compose `gaia-backend` service has `depends_on: service_healthy`
 *   for every infra container — a DB that is down keeps the backend
 *   unstarted or makes its docker healthcheck (`curl -f /health`) fail, which
 *   surfaces here as `api_down`. A separate DB liveness probe from the web
 *   layer would be redundant and would require bundling DB drivers into the
 *   frontend image.
 * - If the API were extended to return 503 when any DB is down directly from
 *   `/health`, this proxy's 503 `api_down` would continue to be the correct
 *   externally-visible signal — no web change needed.
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
        return NextResponse.json({ status: "setup_required" }, { status: 200 });
      }
      return NextResponse.json({ status: "ok" }, { status: 200 });
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return NextResponse.json({ status: "api_down" }, { status: 503 });
  }
}
