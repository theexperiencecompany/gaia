/**
 * A link page resolves during SSR, so the API sees the web server, not the
 * viewer. The server names the viewer, with the token that makes the API believe it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { viewerForwardingHeaders } from "@/lib/viewerForwardingHeaders";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("viewerForwardingHeaders", () => {
  it("names the Cloudflare-verified viewer with the resolver token", () => {
    vi.stubEnv("INTERNAL_RESOLVER_TOKEN", "t0ken");
    const incoming = new Headers({
      "cf-connecting-ip": "198.51.100.7",
      "x-forwarded-for": "203.0.113.9, 10.0.0.1",
    });

    expect(viewerForwardingHeaders(incoming)).toEqual({
      "X-Gaia-Viewer-IP": "198.51.100.7",
      "X-Gaia-Internal": "t0ken",
    });
  });

  it("falls back to the proxy's first forwarded address off Cloudflare", () => {
    vi.stubEnv("INTERNAL_RESOLVER_TOKEN", "t0ken");
    const incoming = new Headers({
      "x-forwarded-for": "203.0.113.9, 10.0.0.1",
    });

    expect(viewerForwardingHeaders(incoming)["X-Gaia-Viewer-IP"]).toBe(
      "203.0.113.9",
    );
  });

  it("sends nothing without a token, which the API would not believe", () => {
    vi.stubEnv("INTERNAL_RESOLVER_TOKEN", "");
    const incoming = new Headers({ "cf-connecting-ip": "198.51.100.7" });

    expect(viewerForwardingHeaders(incoming)).toEqual({});
  });

  it("sends nothing when the request names no viewer", () => {
    vi.stubEnv("INTERNAL_RESOLVER_TOKEN", "t0ken");

    expect(viewerForwardingHeaders(new Headers())).toEqual({});
  });
});
