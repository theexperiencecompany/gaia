/** The health probe must answer with a status even when the API base is unusable. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/health/route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("GET /api/health", () => {
  it("reports api_unconfigured when only a same-origin base exists", async () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "/api/v1/");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const res = await GET();

    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ status: "api_unconfigured" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reports ok on hosted GAIA without asking for setup status", async () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "https://api.heygaia.io/api/v1/");
    const fetchSpy = vi.fn(async (_url: string) => new Response("ok"));
    vi.stubGlobal("fetch", fetchSpy);

    const res = await GET();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
    expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual([
      "https://api.heygaia.io/api/v1/health",
    ]);
  });

  it("probes the internal API base", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    vi.stubEnv("API_BASE_URL_INTERNAL", "http://gaia-backend:8000/api/v1/");
    const fetchSpy = vi.fn(async (url: string) =>
      url.endsWith("/setup/status")
        ? Response.json({ needs_setup: true })
        : new Response("ok"),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const res = await GET();

    expect(await res.json()).toEqual({ status: "setup_required" });
    expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual([
      "http://gaia-backend:8000/api/v1/health",
      "http://gaia-backend:8000/api/v1/setup/status",
    ]);
  });
});
