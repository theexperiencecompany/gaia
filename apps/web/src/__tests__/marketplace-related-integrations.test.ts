/**
 * Which integrations a marketplace page links as related: every integration must
 * be linked from its neighbours, not only from the directory, so none is orphaned.
 */
import { describe, expect, it } from "vitest";

import {
  RELATED_INTEGRATIONS_LIMIT,
  relatedIntegrations,
} from "@/features/integrations/lib/relatedIntegrations";
import type { CommunityIntegration } from "@/features/integrations/types";

import MARKETPLACE_CONFIG from "./fixtures/integrations-config.json";

function card(
  slug: string,
  category: string,
  source?: "platform",
): CommunityIntegration {
  return {
    integrationId: slug,
    slug,
    name: slug,
    description: "",
    category,
    iconUrl: null,
    cloneCount: 0,
    toolCount: 0,
    tools: [],
    publishedAt: null,
    creator: null,
    source,
  };
}

const NATIVE = [
  card("gmail", "communication", "platform"),
  card("notion", "productivity", "platform"),
  card("slack", "communication", "platform"),
  card("todoist", "productivity", "platform"),
  card("zoom", "communication", "platform"),
  card("yelp", "lifestyle", "platform"),
];
const COMMUNITY = [
  card("granola-mcp-productivity", "productivity"),
  card("resend-mcp-communication", "communication"),
  card("dropbox-mcp-productivity", "productivity"),
];

const slugs = (items: readonly CommunityIntegration[]) =>
  items.map((item) => item.slug);

describe("relatedIntegrations", () => {
  it("links a native page to the natives after it, its category first", () => {
    expect(slugs(relatedIntegrations(NATIVE[2], NATIVE, COMMUNITY, 4))).toEqual(
      ["zoom", "gmail", "todoist", "yelp"],
    );
  });

  it("fills a lone category with GAIA's other integrations", () => {
    expect(slugs(relatedIntegrations(NATIVE[5], NATIVE, COMMUNITY, 3))).toEqual(
      ["gmail", "notion", "slack"],
    );
  });

  it("links a community page to its category's community, then natives", () => {
    expect(
      slugs(relatedIntegrations(COMMUNITY[0], NATIVE, COMMUNITY, 4)),
    ).toEqual(["dropbox-mcp-productivity", "notion", "todoist", "gmail"]);
  });

  it("links every live native integration from at least two other pages", () => {
    const native = MARKETPLACE_CONFIG.integrations.map((item) =>
      card(item.slug, item.category, "platform"),
    );
    const incoming = new Map(native.map((item) => [item.slug, 0]));
    for (const page of native) {
      for (const linked of relatedIntegrations(page, native, [])) {
        incoming.set(linked.slug, (incoming.get(linked.slug) ?? 0) + 1);
      }
    }
    const underLinked = [...incoming].filter(([, count]) => count < 2);
    expect(underLinked).toEqual([]);
    expect(relatedIntegrations(native[0], native, []).length).toBe(
      RELATED_INTEGRATIONS_LIMIT,
    );
  });
});
