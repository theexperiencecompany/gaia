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

  it("names each alternative guide by its tool, not a repeated phrase", () => {
    const alternatives = ["Airtable", "Akiflow", "Any.do", "Asana"].map(
      (name) => ({ slug: name.toLowerCase(), name }),
    );
    const html = renderToStaticMarkup(
      <BestHubAlternativeLinks title="Guides" alternatives={alternatives} />,
    );
    const guideTexts = anchors(html)
      .filter(({ href }) => href.startsWith("/alternative-to/"))
      .map(({ text }) => text.toLowerCase());
    const words = guideTexts.flatMap((text) => text.split(/\s+/));
    const repeated = words.filter(
      (word, index) => words.indexOf(word) !== index,
    );
    expect(repeated).toEqual([]);
  });
});
