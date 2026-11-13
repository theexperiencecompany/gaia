/**
 * `renderCardText`: a card as CommonMark — what a text-only platform shows and
 * the exact record reported to the agent. Platform conversion runs through the
 * real `renderForPlatform` chokepoint, as it does at send time.
 */
import {
  type Card,
  type CardLinkAction,
  renderCardText,
  renderForPlatform,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

function makeCard(overrides: Partial<Card> = {}): Card {
  return { title: "Test Title", blocks: [], actions: [], ...overrides };
}

const DASHBOARD: CardLinkAction = {
  kind: "link",
  label: "Dashboard",
  url: "https://app.gaia.com",
};

describe("renderCardText", () => {
  it("bolds the title in CommonMark", () => {
    expect(renderCardText(makeCard())).toBe("**Test Title**");
  });

  it("renders the title as Slack *title* through the platform pipeline", () => {
    const result = renderForPlatform(renderCardText(makeCard()), "slack");
    expect(result).toContain("*Test Title*");
    expect(result).not.toContain("**Test Title**");
  });

  it("keeps blocks in order: text, then each field as bold label over value", () => {
    const result = renderCardText(
      makeCard({
        blocks: [
          { kind: "text", markdown: "Some info" },
          {
            kind: "fields",
            fields: [
              { label: "Field1", value: "val1" },
              { label: "Field2", value: "val2" },
            ],
          },
        ],
      }),
    );
    expect(result).toBe(
      "**Test Title**\n\nSome info\n\n**Field1**\nval1\n\n**Field2**\nval2",
    );
  });

  it("writes link actions as [label](url) so every platform can localise them", () => {
    const result = renderCardText(makeCard({ actions: [DASHBOARD] }));
    expect(result).toContain("[Dashboard](https://app.gaia.com)");
  });

  it("renders links as Slack <url|label>, pipe-separated", () => {
    const result = renderForPlatform(
      renderCardText(
        makeCard({
          actions: [
            { kind: "link", label: "A", url: "https://a.com" },
            { kind: "link", label: "B", url: "https://b.com" },
          ],
        }),
      ),
      "slack",
    );
    expect(result).toContain("<https://a.com|A> | <https://b.com|B>");
  });

  it("renders links as WhatsApp label (url)", () => {
    const result = renderForPlatform(
      renderCardText(makeCard({ actions: [DASHBOARD] })),
      "whatsapp",
    );
    expect(result).toContain("Dashboard (https://app.gaia.com)");
    expect(result).not.toContain("[Dashboard](https://app.gaia.com)");
  });

  it("puts the author first and the italic footer last", () => {
    const result = renderCardText(
      makeCard({
        author: { name: "GAIA Bot" },
        footer: "Powered by GAIA",
        actions: [DASHBOARD],
      }),
    );
    expect(result.startsWith("GAIA Bot\n\n**Test Title**")).toBe(true);
    expect(result.endsWith("_Powered by GAIA_")).toBe(true);
  });

  it("renders a titleless card as its body alone", () => {
    const result = renderCardText({
      blocks: [{ kind: "text", markdown: "Just a notice." }],
      actions: [],
    });
    expect(result).toBe("Just a notice.");
  });
});
