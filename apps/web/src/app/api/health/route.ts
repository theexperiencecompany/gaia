import { NextResponse } from "next/server";
import { isSelfhostWeb } from "@/lib/selfhost";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const HEALTH_TIMEOUT_MS = 5000;

/**
 * Reverse-proxy health probe (`GET /api/health`, no auth, 5s timeout).
 *
 * 503 for `api_down` or `api_unconfigured` (no absolute API base URL);
 * `setup_required` is 200 so LB checks stay healthy during the first-run
 * wizard; hosted GAIA has no setup surface, so it stops at reachability.
 * Infra health is the API's `GET /health` — the web has no DB clients.
 */
export async function GET() {
  const apiBase = getServerApiBaseUrl();
  if (!apiBase) {
    console.error(
      "[health] API base URL is unset or not an absolute URL; cannot probe the API",
    );
    return NextResponse.json({ status: "api_unconfigured" }, { status: 503 });
  }

  const healthUrl = `${apiBase}/health`;
  const setupStatusUrl = `${apiBase}/setup/status`;

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

  if (!isSelfhostWeb()) {
    return NextResponse.json({ status: "ok" }, { status: 200 });
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
