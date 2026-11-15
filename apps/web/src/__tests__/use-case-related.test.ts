/**
 * Which use cases a use-case page links as related: every curated use case must
 * be linked from its neighbours, not only from the hub, so none is orphaned.
 */
import { describe, expect, it } from "vitest";

import {
  RELATED_USE_CASES_LIMIT,
  relatedUseCases,
} from "@/features/use-cases/lib/relatedUseCases";

const curated = (slug: string, ...categories: string[]) => ({
  slug,
  categories,
});

const EXPLORE = [
  curated("inbox-triage", "Email", "featured"),
  curated("morning-briefing", "Home admin", "featured"),
  curated("auto-draft-replies", "Email"),
  curated("rent-reminder", "Home admin"),
  curated("follow-up-reminders", "Email", "featured"),
  curated("save-the-bug", "Dev"),
];

const slugs = (items: readonly { slug: string }[]) =>
  items.map((item) => item.slug);

describe("relatedUseCases", () => {
  it("links the use cases after this one, its own category first, a third of the list at most", () => {
    expect(
      slugs(relatedUseCases({ slug: "auto-draft-replies" }, EXPLORE, 3)),
    ).toEqual(["follow-up-reminders", "rent-reminder", "save-the-bug"]);
  });

  it("ranks by the page's own category, not the shared featured tag", () => {
    expect(
      slugs(relatedUseCases({ slug: "morning-briefing" }, EXPLORE, 2)),
    ).toEqual(["rent-reminder", "auto-draft-replies"]);
  });

  it("gives a community workflow the curated featured use cases first", () => {
    expect(
      slugs(relatedUseCases({ slug: "my-own-workflow" }, EXPLORE, 4)),
    ).toEqual([
      "inbox-triage",
      "morning-briefing",
      "auto-draft-replies",
      "rent-reminder",
    ]);
  });

  it("keeps two thirds of the links outside its own category, so one topic does not repeat down the page", () => {
    const related = relatedUseCases({ slug: "auto-draft-replies" }, EXPLORE, 2);
    expect(slugs(related)).toEqual(["follow-up-reminders", "rent-reminder"]);
  });

  it("links every curated use case from at least two other pages", () => {
    const incoming = new Map(EXPLORE.map((item) => [item.slug, 0]));
    for (const page of EXPLORE) {
      const related = relatedUseCases(page, EXPLORE);
      expect(slugs(related)).not.toContain(page.slug);
      for (const linked of related) {
        incoming.set(linked.slug, (incoming.get(linked.slug) ?? 0) + 1);
      }
    }
    expect([...incoming].filter(([, count]) => count < 2)).toEqual([]);
    expect(relatedUseCases(EXPLORE[0], EXPLORE)).toHaveLength(
      Math.min(RELATED_USE_CASES_LIMIT, EXPLORE.length - 1),
    );
  });
});
