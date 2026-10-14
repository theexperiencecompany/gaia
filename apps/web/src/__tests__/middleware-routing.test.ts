/**
 * The edge middleware: heygaia.link slugs bounce to /l/<slug> whatever word they
 * start with, and the locale-invariant paths are never handed to next-intl.
 */

import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

const intlHandler = vi.hoisted(() => vi.fn());
vi.mock("next-intl/middleware", () => ({ default: () => intlHandler }));

import middleware, { config } from "@/middleware";

const matches = (path: string) =>
  config.matcher.some((pattern) => new RegExp(`^${pattern}$`).test(path));

function request(url: string): NextRequest {
  return new NextRequest(url, { headers: { host: new URL(url).host } });
}

describe("heygaia.link slugs", () => {
  it.each(["apiXk3Lm9Qz", "connectAb12", "ingestZZ9xy", "sitemapQ1w2"])(
    "redirects %s even though it starts with a bypassed word",
    (slug) => {
      expect(matches(`/${slug}`)).toBe(true);

      const response = middleware(request(`https://heygaia.link/${slug}`));

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe(
        `https://heygaia.io/l/${slug}`,
      );
      expect(intlHandler).not.toHaveBeenCalled();
    },
  );
});

describe("locale-invariant paths on the app host", () => {
  it.each(["/connect", "/connect/c0de", "/api/blog", "/ingest/e"])(
    "passes %s through without next-intl",
    (path) => {
      const response = middleware(request(`https://heygaia.io${path}`));

      expect(response.headers.get("x-middleware-next")).toBe("1");
      expect(intlHandler).not.toHaveBeenCalled();
    },
  );

  it("skips build assets and files entirely", () => {
    expect(matches("/_next/static/chunk.js")).toBe(false);
    expect(matches("/favicon.ico")).toBe(false);
  });
});
