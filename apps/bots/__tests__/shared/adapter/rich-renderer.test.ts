import { describe, it, expect } from "vitest";
import { richMessageToMarkdown } from "@gaia/shared";
import type { RichMessage } from "@gaia/shared";

// ---------------------------------------------------------------------------
// Helper to build a minimal RichMessage
// ---------------------------------------------------------------------------
function makeMsg(overrides: Partial<RichMessage> = {}): RichMessage {
  return {
    type: "embed",
    title: "Test Title",
    fields: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// richMessageToMarkdown
// ---------------------------------------------------------------------------
describe("richMessageToMarkdown", () => {
  // -- Title formatting per platform ---------------------------------------
  it("formats title with *title* for Telegram", () => {
    const result = richMessageToMarkdown(makeMsg(), "telegram");
    expect(result).toContain("*Test Title*");
    expect(result).not.toContain("**Test Title**");
  });

  it("formats title with **title** for Discord", () => {
    const result = richMessageToMarkdown(makeMsg(), "discord");
    expect(result).toContain("**Test Title**");
  });

  it("formats title with *title* for Slack", () => {
    const result = richMessageToMarkdown(makeMsg(), "slack");
    expect(result).toContain("*Test Title*");
    expect(result).not.toContain("**Test Title**");
  });

  // -- Description ---------------------------------------------------------
  it("includes description when provided", () => {
    const result = richMessageToMarkdown(
      makeMsg({ description: "Some info" }),
      "telegram",
    );
    expect(result).toContain("Some info");
  });

  // -- Fields --------------------------------------------------------------
  it("formats fields with bold names", () => {
    const msg = makeMsg({
      fields: [{ name: "Status", value: "Online" }],
    });

    const telegramResult = richMessageToMarkdown(msg, "telegram");
    expect(telegramResult).toContain("*Status*");
    expect(telegramResult).toContain("Online");

    const discordResult = richMessageToMarkdown(msg, "discord");
    expect(discordResult).toContain("**Status**");
  });

  // -- Links ---------------------------------------------------------------
  it("formats links as <url|label> for Slack", () => {
    const msg = makeMsg({
      links: [{ label: "Dashboard", url: "https://app.gaia.com" }],
    });
    const result = richMessageToMarkdown(msg, "slack");
    expect(result).toContain("<https://app.gaia.com|Dashboard>");
  });

  it("formats links as [label](url) for Telegram", () => {
    const msg = makeMsg({
      links: [{ label: "Dashboard", url: "https://app.gaia.com" }],
    });
    const result = richMessageToMarkdown(msg, "telegram");
    expect(result).toContain("[Dashboard](https://app.gaia.com)");
  });

  it("formats links as [label](url) for Discord", () => {
    const msg = makeMsg({
      links: [{ label: "Dashboard", url: "https://app.gaia.com" }],
    });
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("[Dashboard](https://app.gaia.com)");
  });

  // -- Footer --------------------------------------------------------------
  it("italicizes footer", () => {
    const result = richMessageToMarkdown(
      makeMsg({ footer: "Powered by GAIA" }),
      "telegram",
    );
    expect(result).toContain("_Powered by GAIA_");
  });

  // -- Author name ---------------------------------------------------------
  it("includes author name", () => {
    const result = richMessageToMarkdown(
      makeMsg({ authorName: "GAIA Bot" }),
      "telegram",
    );
    expect(result).toContain("GAIA Bot");
  });

  // -- Empty optional sections omitted -------------------------------------
  it("omits empty fields, links, and footer", () => {
    const msg = makeMsg({
      fields: [],
      links: [],
      footer: undefined,
      description: undefined,
      authorName: undefined,
    });
    const result = richMessageToMarkdown(msg, "telegram");
    // Should only have the title
    expect(result.trim()).toBe("*Test Title*");
  });

  // -- Defaults to telegram ------------------------------------------------
  it("defaults to telegram platform when none specified", () => {
    const result = richMessageToMarkdown(makeMsg());
    // Telegram uses single asterisks for bold
    expect(result).toContain("*Test Title*");
    expect(result).not.toContain("**Test Title**");
  });

  // -- Multiple fields and links -------------------------------------------
  it("separates multiple fields with double newlines", () => {
    const msg = makeMsg({
      fields: [
        { name: "Field1", value: "val1" },
        { name: "Field2", value: "val2" },
      ],
    });
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("**Field1**\nval1");
    expect(result).toContain("**Field2**\nval2");
  });

  it("joins multiple links with pipe separator", () => {
    const msg = makeMsg({
      links: [
        { label: "A", url: "https://a.com" },
        { label: "B", url: "https://b.com" },
      ],
    });
    const result = richMessageToMarkdown(msg, "slack");
    expect(result).toContain("<https://a.com|A> | <https://b.com|B>");
  });
});
