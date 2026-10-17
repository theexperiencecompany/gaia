/**
 * Server code can only fetch an absolute URL. The self-host image bakes a
 * same-origin "/api/v1/" for browsers; on the server that must read as "no API
 * configured" rather than a base every fetch fails (or stalls the build) on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("getServerApiBaseUrl", () => {
  it("prefers the internal URL over the public one", () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "http://gaia-backend:8000/api/v1/");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "/api/v1/");

    expect(getServerApiBaseUrl()).toBe("http://gaia-backend:8000/api/v1");
  });

  it("falls back to an absolute public URL", () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000/api/v1/");

    expect(getServerApiBaseUrl()).toBe("http://localhost:8000/api/v1");
  });

  it("is null when only a same-origin public base exists", () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "/api/v1/");

    expect(getServerApiBaseUrl()).toBeNull();
  });
});
