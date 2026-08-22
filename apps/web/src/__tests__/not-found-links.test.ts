/**
 * The 404 page is the only recovery surface for agents/crawlers that hit a
 * dead URL (the response keeps its real HTTP 404 status). These tests pin
 * the contract of the recovery links it renders: every entry must be a
 * complete, honest, server-renderable anchor pointing at a real target.
 */
import { describe, expect, it } from "vitest";
import { NOT_FOUND_LINKS } from "@/lib/not-found-links";

describe("NOT_FOUND_LINKS", () => {
  it("stays a compact recovery hint, not a sitemap dump", () => {
    expect(NOT_FOUND_LINKS.length).toBeGreaterThan(0);
    expect(NOT_FOUND_LINKS.length).toBeLessThanOrEqual(5);
  });

  it.each(NOT_FOUND_LINKS.map((l) => [l.href] as const))(
    "entry %s has non-empty name, href and description",
    (href) => {
      const link = NOT_FOUND_LINKS.find((l) => l.href === href);
      expect(link).toBeDefined();
      expect(link?.name.trim()).not.toBe("");
      expect(link?.href.trim()).not.toBe("");
      expect(link?.description.trim()).not.toBe("");
    },
  );

  it("has no duplicate names or hrefs", () => {
    const names = NOT_FOUND_LINKS.map((l) => l.name);
    const hrefs = NOT_FOUND_LINKS.map((l) => l.href);
    expect(new Set(names).size).toBe(names.length);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("uses only root-relative internal paths or absolute https URLs", () => {
    for (const { href } of NOT_FOUND_LINKS) {
      if (href.startsWith("/")) {
        // Protocol-relative "//host" is an open-redirect smell, not an internal path.
        expect(href.startsWith("//")).toBe(false);
      } else {
        const url = new URL(href);
        expect(url.protocol).toBe("https:");
        expect(url.hostname).not.toBe("");
      }
    }
  });

  it("covers the required agent recovery targets", () => {
    const hrefs = NOT_FOUND_LINKS.map((l) => l.href);
    expect(hrefs).toContain("/");
    expect(hrefs).toContain("/llms.txt");
    // Primary sitemap segment: /sitemap/[id]/route.ts serves id 0 (static pages)
    // as /sitemap/0.xml — same shape the /api/sitemap-xml index emits.
    expect(hrefs).toContain("/sitemap/0.xml");
    expect(hrefs).toContain("https://docs.heygaia.io");
  });

  it("anchors are descriptive — never bare 'click here' text", () => {
    for (const { name } of NOT_FOUND_LINKS) {
      expect(name.toLowerCase()).not.toBe("click here");
      expect(name.toLowerCase()).not.toBe("here");
      expect(name.toLowerCase()).not.toBe("link");
    }
  });

  it("describes each destination rather than repeating its name", () => {
    for (const { name, description } of NOT_FOUND_LINKS) {
      expect(description.toLowerCase()).not.toBe(name.toLowerCase());
    }
  });
});
