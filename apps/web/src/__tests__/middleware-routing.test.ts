/**
 * The edge middleware: link-host slugs bounce to /l/<slug> whatever word they
 * start with, and the locale-invariant paths are never handed to next-intl.
 */

import { NextRequest, NextResponse } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

const intlHandler = vi.hoisted(() => vi.fn());
vi.mock("next-intl/middleware", () => ({ default: () => intlHandler }));

import middleware, { config } from "@/middleware";

const matches = (path: string) =>
  config.matcher.some((pattern) => new RegExp(`^${pattern}$`).test(path));

function request(url: string): NextRequest {
  return new NextRequest(url, { headers: { host: new URL(url).host } });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("heygaia.link slugs", () => {
  it.each(["apiXk3Lm9Qz", "connectAb12", "ingestZZ9xy", "sitemapQ1w2"])(
    "redirects %s even though it starts with a bypassed word",
    async (slug) => {
      vi.stubEnv("GAIA_LINK_HOST", "heygaia.link");
      expect(matches(`/${slug}`)).toBe(true);

      const response = await middleware(
        request(`https://heygaia.link/${slug}`),
      );

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe(
        `https://heygaia.io/l/${slug}`,
      );
      expect(intlHandler).not.toHaveBeenCalled();
    },
  );
});

describe("the link host is the deployment's, read per request", () => {
  it("redirects slugs on the host the runtime names", async () => {
    vi.stubEnv("GAIA_LINK_HOST", "go.example.org");

    const response = await middleware(
      request("https://go.example.org/abcdefghijk"),
    );

    expect(response.status).toBe(307);
    expect(new URL(response.headers.get("location") ?? "").pathname).toBe(
      "/l/abcdefghijk",
    );
  });

  it("treats no host as a link host when the runtime names none", async () => {
    vi.stubEnv("GAIA_LINK_HOST", "");
    intlHandler.mockReturnValueOnce(NextResponse.next());

    const response = await middleware(
      request("https://heygaia.link/abcdefghijk"),
    );

    expect(response.status).not.toBe(307);
    expect(intlHandler).toHaveBeenCalledOnce();
  });
});

describe("locale-invariant paths on the app host", () => {
  it.each(["/connect", "/connect/c0de", "/api/blog", "/ingest/e", "/feed"])(
    "passes %s through without next-intl",
    async (path) => {
      const response = await middleware(request(`https://heygaia.io${path}`));

      expect(response.headers.get("x-middleware-next")).toBe("1");
      expect(intlHandler).not.toHaveBeenCalled();
    },
  );

  it("skips build assets and files entirely", () => {
    expect(matches("/_next/static/chunk.js")).toBe(false);
    expect(matches("/favicon.ico")).toBe(false);
  });
});
