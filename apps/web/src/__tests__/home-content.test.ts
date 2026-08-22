import { describe, expect, it } from "vitest";

import {
  getHomeSection,
  HERO_TITLE_LINES,
  HOME_CONTENT,
} from "@/features/landing/content/home-content";

const isInternalHref = (href: string): boolean =>
  href.startsWith("/") || href.startsWith("https://");

describe("HOME_CONTENT", () => {
  it("has a complete, non-empty hero block", () => {
    expect(HOME_CONTENT.metaTitle.trim()).toBeTruthy();
    expect(HOME_CONTENT.heroEyebrow.trim()).toBeTruthy();
    expect(HOME_CONTENT.heroTitle.trim()).toBeTruthy();
    expect(HOME_CONTENT.heroSubtitle.trim()).toBeTruthy();
    // The canonical title is single-line text — text-only variants render it
    // as one H1, so it must never carry embedded line breaks.
    expect(HOME_CONTENT.heroTitle).not.toMatch(/\n/);
  });

  it("has at least one CTA with a label and an href", () => {
    expect(HOME_CONTENT.heroCtas.length).toBeGreaterThan(0);
    for (const cta of HOME_CONTENT.heroCtas) {
      expect(cta.label.trim()).toBeTruthy();
      expect(isInternalHref(cta.href)).toBe(true);
    }
  });

  it("renders the hero title as the designed two-line lockup", () => {
    // Drift guard: the display lines must always compose the canonical title.
    expect(HERO_TITLE_LINES.join(" ")).toBe(HOME_CONTENT.heroTitle);
    expect(HERO_TITLE_LINES.length).toBeGreaterThan(1);
  });

  it("orders sections uniquely with non-empty copy", () => {
    expect(HOME_CONTENT.sections.length).toBeGreaterThan(0);
    const ids = HOME_CONTENT.sections.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const section of HOME_CONTENT.sections) {
      expect(section.heading.trim()).toBeTruthy();
      expect(section.description.trim()).toBeTruthy();
    }
  });

  it("covers every homepage section in render order", () => {
    expect(HOME_CONTENT.sections.map((s) => s.id)).toEqual([
      "runs-your-day",
      "integrations",
      "workflows",
      "memory",
      "bots",
      "use-cases",
      "open-source",
      "pricing",
      "faq",
      "get-started",
    ]);
  });
});

describe("getHomeSection", () => {
  it("returns the section for a known id", () => {
    const section = getHomeSection("memory");
    expect(section.id).toBe("memory");
    expect(section.heading).toBe("It remembers, so you don't");
  });

  it("throws on an unknown id instead of returning undefined", () => {
    expect(() => getHomeSection("does-not-exist")).toThrow(
      'Unknown home section id: "does-not-exist"',
    );
  });
});
