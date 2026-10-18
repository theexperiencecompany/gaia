/** Glossary terms link only to /automate combos that render, and only where the term is about connecting tools. */
import { describe, expect, it } from "vitest";

import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllComboSlugs } from "@/features/integrations/data/combosData";
import { isRedirectedPath } from "@/lib/canonicalLinks";

const MIN_LINKS = 2;
const MAX_LINKS = 4;

/** Terms with no tool-to-tool automation to demonstrate. */
const UNLINKED_TERMS = [
  "gdpr",
  "fine-tuning",
  "multimodal-ai",
  "pomodoro-technique",
];

describe("glossary automation links", () => {
  it("point every term's combos at live, non-redirected /automate pages", async () => {
    const [terms, comboSlugs] = await Promise.all([
      getAllGlossaryTerms(),
      getAllComboSlugs(),
    ]);
    const liveCombos = new Set(comboSlugs);
    const broken = terms.flatMap((term) =>
      (term.relatedAutomations ?? []).flatMap((slug) => {
        const path = `/automate/${slug}`;
        if (!liveCombos.has(slug)) return [`${term.slug} -> ${path} (missing)`];
        if (isRedirectedPath(path))
          return [`${term.slug} -> ${path} (redirected)`];
        return [];
      }),
    );
    expect(broken).toEqual([]);
  });

  it(`gives each linked term ${MIN_LINKS}-${MAX_LINKS} distinct combos`, async () => {
    const linked = (await getAllGlossaryTerms()).filter(
      (term) => term.relatedAutomations !== undefined,
    );
    expect(linked.map((term) => term.slug)).toEqual(
      expect.arrayContaining(["webhook", "cron-job", "workflow-automation"]),
    );
    for (const term of linked) {
      const slugs = term.relatedAutomations ?? [];
      expect(slugs.length, term.slug).toBeGreaterThanOrEqual(MIN_LINKS);
      expect(slugs.length, term.slug).toBeLessThanOrEqual(MAX_LINKS);
      expect(new Set(slugs).size, term.slug).toBe(slugs.length);
    }
  });

  it("leaves terms unrelated to connecting tools without combo links", async () => {
    const terms = await getAllGlossaryTerms();
    for (const slug of UNLINKED_TERMS) {
      const term = terms.find((candidate) => candidate.slug === slug);
      expect(term, slug).toBeDefined();
      expect(term?.relatedAutomations, slug).toBeUndefined();
    }
  });
});
