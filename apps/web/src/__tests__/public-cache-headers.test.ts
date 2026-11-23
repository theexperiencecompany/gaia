/** Shared caches may hold the hosted public site, never a self-host page that renders live setup status. */
import type { NextConfig } from "next";
import { getPathMatch } from "next/dist/shared/lib/router/utils/path-match";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

let headers: NonNullable<NextConfig["headers"]>;

beforeAll(async () => {
  vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "phc_test_token");
  const { default: nextConfig } = await import("../../next.config.mjs");
  if (!nextConfig.headers)
    throw new Error("next.config.mjs defines no headers()");
  headers = nextConfig.headers;
});

afterEach(() => {
  vi.unstubAllEnvs();
});

async function cacheControl(pathname: string): Promise<string | undefined> {
  let value: string | undefined;
  for (const rule of await headers()) {
    const match = getPathMatch(rule.source, {
      strict: true,
      removeUnnamedParams: true,
    });
    if (match(pathname) === false) continue;
    for (const header of rule.headers) {
      if (header.key.toLowerCase() === "cache-control") value = header.value;
    }
  }
  return value;
}

describe("public Cache-Control", () => {
  it.each(["/", "/de", "/signup", "/compare/notion"])(
    "the hosted build lets shared caches hold %s",
    async (pathname) => {
      vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");
      expect(await cacheControl(pathname)).toMatch(/^public, .*s-maxage=60/);
    },
  );

  it.each(["/signup", "/fr/signup", "/compare/notion"])(
    "the self-host build leaves %s to its own headers",
    async (pathname) => {
      vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
      expect(await cacheControl(pathname)).toBeUndefined();
    },
  );
});
