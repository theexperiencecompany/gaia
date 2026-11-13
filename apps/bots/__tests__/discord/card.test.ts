/**
 * `renderDiscordCard`: a shared Card as a native Discord embed plus link-button
 * rows. Runs against the real discord.js builders and asserts on their JSON —
 * the payload Discord actually receives.
 */
import type { Card } from "@gaia/shared/bots";
import { ButtonStyle, ComponentType } from "discord.js";
import { describe, expect, it } from "vitest";
import { renderDiscordCard } from "../../discord/src/card";

function makeCard(overrides: Partial<Card> = {}): Card {
  return { title: "Test Title", blocks: [], actions: [], ...overrides };
}

function embedJson(card: Card) {
  const embed = renderDiscordCard(card).embeds[0];
  if (!embed || !("toJSON" in embed)) throw new Error("no embed builder");
  return embed.toJSON();
}

describe("renderDiscordCard — embed", () => {
  it("joins text blocks into the description", () => {
    const data = embedJson(
      makeCard({
        blocks: [
          { kind: "text", markdown: "First." },
          { kind: "text", markdown: "Second." },
        ],
      }),
    );
    expect(data.title).toBe("Test Title");
    expect(data.description).toBe("First.\n\nSecond.");
  });

  it("maps fields with the inline flag, defaulting to false", () => {
    const data = embedJson(
      makeCard({
        blocks: [
          {
            kind: "fields",
            fields: [
              { label: "Plan", value: "Pro", inline: true },
              { label: "Apps", value: "Gmail" },
            ],
          },
        ],
      }),
    );
    expect(data.fields).toEqual([
      { name: "Plan", value: "Pro", inline: true },
      { name: "Apps", value: "Gmail", inline: false },
    ]);
  });

  it("maps accent, footer, thumbnail, author and timestamp", () => {
    const data = embedJson(
      makeCard({
        accent: "brand",
        footer: "This link works for 60 minutes.",
        thumbnailUrl: "https://gaia.test/avatar.png",
        author: { name: "Aryan", iconUrl: "https://gaia.test/a.png" },
        timestamp: true,
      }),
    );
    expect(data.color).toBe(0x7c3aed);
    expect(data.footer?.text).toBe("This link works for 60 minutes.");
    expect(data.thumbnail?.url).toBe("https://gaia.test/avatar.png");
    expect(data.author).toEqual({
      name: "Aryan",
      icon_url: "https://gaia.test/a.png",
    });
    expect(data.timestamp).toEqual(expect.any(String));
  });

  it("omits every optional part on a minimal card", () => {
    const data = embedJson(makeCard());
    expect(data.description).toBeUndefined();
    expect(data.fields).toBeUndefined();
    expect(data.color).toBeUndefined();
    expect(data.footer).toBeUndefined();
    expect(data.timestamp).toBeUndefined();
  });
});

describe("renderDiscordCard — link buttons", () => {
  it("renders each action as a link button, not as embed text", () => {
    const { components, embeds } = renderDiscordCard(
      makeCard({
        actions: [
          {
            kind: "link",
            label: "Reconnect PostHog",
            url: "https://gaia.test/connect/abc",
          },
        ],
      }),
    );
    const row = components[0];
    if (!row || !("toJSON" in row)) throw new Error("no action row");
    expect(row.toJSON()).toEqual({
      type: ComponentType.ActionRow,
      components: [
        {
          type: ComponentType.Button,
          style: ButtonStyle.Link,
          label: "Reconnect PostHog",
          url: "https://gaia.test/connect/abc",
        },
      ],
    });
    const embed = embeds[0];
    if (!embed || !("toJSON" in embed)) throw new Error("no embed builder");
    expect(JSON.stringify(embed.toJSON())).not.toContain("gaia.test/connect");
  });

  it("starts a new row after five buttons, Discord's per-row maximum", () => {
    const actions = Array.from({ length: 6 }, (_, i) => ({
      kind: "link" as const,
      label: `Link ${i}`,
      url: `https://gaia.test/${i}`,
    }));
    const { components } = renderDiscordCard(makeCard({ actions }));
    expect(components).toHaveLength(2);
  });

  it("sends no rows when the card has no actions", () => {
    expect(renderDiscordCard(makeCard()).components).toEqual([]);
  });
});
