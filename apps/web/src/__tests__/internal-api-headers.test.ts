/**
 * The web server's API requests carry INTERNAL_API_TOKEN so the API counts them
 * apart from viewers, and a page rendered for a viewer names that viewer.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  internalApiHeaders,
  warnWhenInternalApiTokenMissing,
} from "@/lib/internalApiHeaders";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("internalApiHeaders", () => {
  it("sends the token on the server's own requests", () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "t0ken");

    expect(internalApiHeaders()).toEqual({ "X-Gaia-Internal": "t0ken" });
  });

  it("names the Cloudflare-verified viewer a page is rendered for", () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "t0ken");
    const incoming = new Headers({
      "cf-connecting-ip": "198.51.100.7",
      "x-forwarded-for": "203.0.113.9, 10.0.0.1",
    });

    expect(internalApiHeaders(incoming)).toEqual({
      "X-Gaia-Internal": "t0ken",
      "X-Gaia-Viewer-IP": "198.51.100.7",
    });
  });

  it("falls back to the proxy's first forwarded address off Cloudflare", () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "t0ken");
    const incoming = new Headers({
      "x-forwarded-for": "203.0.113.9, 10.0.0.1",
    });

    expect(internalApiHeaders(incoming)["X-Gaia-Viewer-IP"]).toBe(
      "203.0.113.9",
    );
  });

  it("sends nothing without a token, so the API applies its normal limits", () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "");
    const incoming = new Headers({ "cf-connecting-ip": "198.51.100.7" });

    expect(internalApiHeaders(incoming)).toEqual({});
  });
});

describe("warnWhenInternalApiTokenMissing", () => {
  it("is loud when GAIA Cloud's web server boots without the token", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");
    vi.stubEnv("INTERNAL_API_TOKEN", "");
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    warnWhenInternalApiTokenMissing();

    expect(error).toHaveBeenCalledOnce();
    expect(String(error.mock.calls[0][0])).toContain("INTERNAL_API_TOKEN");
    error.mockRestore();
  });

  it.each([
    ["the token is set", { INTERNAL_API_TOKEN: "t0ken" }],
    ["a self-host image", { NEXT_PUBLIC_GAIA_SELFHOST: "true" }],
    ["development", { NODE_ENV: "development" }],
  ])("stays quiet for %s", (_, env) => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");
    vi.stubEnv("INTERNAL_API_TOKEN", "");
    for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value);
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    warnWhenInternalApiTokenMissing();

    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });
});
