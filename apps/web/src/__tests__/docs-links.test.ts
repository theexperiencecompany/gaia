import { describe, expect, it } from "vitest";

import {
  ALTERNATIVE_DOCS_LINKS,
  COMPARE_DOCS_LINKS,
  getAutomateDocsLinks,
  LEARN_DOCS_LINKS,
} from "@/lib/docs-links";

const DOCS = "https://docs.heygaia.io";

describe("docs-links", () => {
  it("maps exact-intent slugs to verified docs URLs", () => {
    expect(COMPARE_DOCS_LINKS.chatgpt?.map((g) => g.url)).toContain(
      `${DOCS}/knowledge/comparisons/gaia-vs-chatgpt`,
    );
    expect(ALTERNATIVE_DOCS_LINKS.zapier?.map((g) => g.url)).toContain(
      `${DOCS}/knowledge/comparisons/gaia-vs-zapier`,
    );
    expect(LEARN_DOCS_LINKS["email-automation"]?.map((g) => g.url)).toContain(
      `${DOCS}/guides/managing-email`,
    );
  });

  it("returns at most two guides per entry with unique URLs", () => {
    for (const section of [
      LEARN_DOCS_LINKS,
      COMPARE_DOCS_LINKS,
      ALTERNATIVE_DOCS_LINKS,
    ]) {
      for (const [slug, guides] of Object.entries(section)) {
        expect(guides.length, slug).toBeLessThanOrEqual(2);
        expect(new Set(guides.map((g) => g.url)).size, slug).toBe(
          guides.length,
        );
      }
    }
  });

  it("derives automate links from tool slugs", () => {
    expect(getAutomateDocsLinks("gmail", "slack").map((g) => g.url)).toEqual([
      `${DOCS}/guides/managing-email`,
      `${DOCS}/guides/slack-bot`,
    ]);
    expect(
      getAutomateDocsLinks("google-calendar", "todoist").map((g) => g.url),
    ).toEqual([
      `${DOCS}/knowledge/how/ai-calendar-scheduling`,
      `${DOCS}/guides/tasks-todos`,
    ]);
  });

  it("dedupes guides when both tools map to the same one", () => {
    expect(getAutomateDocsLinks("notion", "todoist").map((g) => g.url)).toEqual(
      [`${DOCS}/guides/tasks-todos`],
    );
  });

  it("falls back to the workflow guide for unmapped tool pairs", () => {
    expect(getAutomateDocsLinks("zoom", "hubspot").map((g) => g.url)).toEqual([
      `${DOCS}/guides/building-workflows`,
    ]);
  });
});
