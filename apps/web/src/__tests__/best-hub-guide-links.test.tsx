/** The best-of hubs link each other, and their guide lists name tools instead of repeating one phrase per link. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BestHubAlternativeLinks } from "@/components/seo/BestHubGuideLinks";
import { BestHubSiblingLinks } from "@/components/seo/BestHubSiblingLinks";
import { MARKETING_PAGES } from "@/lib/marketingPages";

const BEST_HUBS = MARKETING_PAGES.map((page) => page.path).filter((path) =>
  path.startsWith("/best-ai-"),
);

function anchors(html: string): { href: string; text: string }[] {
  return [...html.matchAll(/<a[^>]*href="([^"]+)"[^>]*>(.*?)<\/a>/g)].map(
    ([, href, text]) => ({ href, text: text.replace(/<!-- -->/g, "") }),
  );
}

describe("best hub guide links", () => {
  it("links every other best-of hub from each one", () => {
    expect(BEST_HUBS.length).toBeGreaterThan(1);
    for (const hub of BEST_HUBS) {
      const html = renderToStaticMarkup(
        <BestHubSiblingLinks currentPath={hub} />,
      );
      expect(
        anchors(html)
          .map(({ href }) => href)
          .sort(),
        hub,
      ).toEqual(BEST_HUBS.filter((path) => path !== hub).sort());
    }
  });

  it("names each alternative guide by its tool, and no two share a label", () => {
    const alternatives = ["Airtable", "Akiflow", "Any.do", "Asana"].map(
      (name) => ({ slug: name.toLowerCase(), name }),
    );
    const html = renderToStaticMarkup(
      <BestHubAlternativeLinks title="Guides" alternatives={alternatives} />,
    );
    const guideTexts = anchors(html)
      .filter(({ href }) => href.startsWith("/alternative-to/"))
      .map(({ text }) => text.toLowerCase());
    // The bare tool name is already the text of the page body's link to the
    // tool, so each guide carries "alternatives" to keep the two distinct for
    // screen readers. What the label must never lose is the tool itself.
    for (const { name } of alternatives) {
      expect(guideTexts).toContain(`${name.toLowerCase()} alternatives`);
    }
    expect(new Set(guideTexts).size).toBe(guideTexts.length);
  });
});
