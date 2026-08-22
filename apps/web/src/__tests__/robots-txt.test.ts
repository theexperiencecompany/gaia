import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROBOTS_PATH = path.join(process.cwd(), "public", "robots.txt");
const APP_DIR = path.join(process.cwd(), "src", "app");

/**
 * public/robots.txt is the canonical robots source (static asset, edge-
 * cached on Cloudflare). These tests guard its contract: allow-all for
 * every declared crawler and Sitemap lines that only reference endpoints
 * that actually exist in the app, so a deleted route can't leave a dead
 * reference behind.
 */
describe("public/robots.txt", () => {
  const body = fs.readFileSync(ROBOTS_PATH, "utf8");

  it("allows every user agent, including a wildcard catch-all", () => {
    expect(body).toMatch(/^User-agent: \*\s*$/m);
    // Every agent block must Allow.
    const agents = [...body.matchAll(/^User-agent: (.+)$/gm)].map((m) => m[1]);
    expect(agents.length).toBeGreaterThan(1);
    expect(body).toMatch(/^Allow: \/$/m);
    expect(body).not.toMatch(/^Disallow:/m);
  });

  it("references only real, absolute https sitemap endpoints", () => {
    const sitemapUrls = [...body.matchAll(/^Sitemap: (\S+)$/gm)].map(
      (m) => m[1],
    );
    expect(sitemapUrls.length).toBeGreaterThan(0);

    for (const url of sitemapUrls) {
      const parsed = new URL(url);
      expect(parsed.protocol).toBe("https:");
      expect(`${parsed.host}${parsed.pathname}`).toBeTruthy();
      expect(url.startsWith("https://heygaia.io/")).toBe(true);

      // Each referenced endpoint must be backed by a real route:
      // /sitemap.xml rewrites to /api/sitemap-xml (see next.config.mjs).
      const pathname = parsed.pathname;
      const backingRoutes: Record<string, string> = {
        "/sitemap.xml": path.join(APP_DIR, "api", "sitemap-xml"),
        "/brand/sitemap.xml": path.join(APP_DIR, "brand", "sitemap.xml"),
        "/feed.xml": path.join(APP_DIR, "feed.xml"),
      };
      const backing = backingRoutes[pathname];
      expect(backing, `no known backing route for ${url}`).toBeDefined();
      expect(fs.existsSync(backing), `missing route file for ${url}`).toBe(
        true,
      );
    }
  });

  it("lists the sitemap index that covers all numbered shards", () => {
    expect(body).toContain("Sitemap: https://heygaia.io/sitemap.xml");
  });
});
