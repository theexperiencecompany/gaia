/**
 * Tests for Discord-specific message rendering.
 *
 * Discord uses EmbedBuilder instead of Markdown text, so it has its own
 * richMessageToEmbed() function that maps RichMessage fields to embed properties.
 *
 * The function is private to the adapter module, so we test it indirectly
 * by verifying the platform-specific bold/link formatting in richMessageToMarkdown
 * and by constructing equivalent logic tests.
 *
 * We also test Discord's platform-specific formatting differences vs Slack/Telegram.
 */

import { describe, it, expect } from "vitest";
import { richMessageToMarkdown } from "@gaia/shared";
import type { RichMessage } from "@gaia/shared";

// ---------------------------------------------------------------------------
// Discord uses **bold** (vs *bold* on Slack/Telegram)
// Discord uses [label](url) links (vs <url|label> on Slack)
// These formatting differences are tested via richMessageToMarkdown.
// ---------------------------------------------------------------------------

describe("Discord rich message formatting", () => {
  const baseMsg: RichMessage = {
    title: "Test Title",
    description: "Test description",
    fields: [],
    links: [],
  };

  it("uses **title** bold syntax for Discord", () => {
    const result = richMessageToMarkdown(baseMsg, "discord");
    expect(result).toContain("**Test Title**");
  });

  it("uses *title* bold syntax for Slack (contrast)", () => {
    const result = richMessageToMarkdown(baseMsg, "slack");
    expect(result).toContain("*Test Title*");
    expect(result).not.toContain("**Test Title**");
  });

  it("uses [label](url) link format for Discord", () => {
    const msg: RichMessage = {
      ...baseMsg,
      links: [{ label: "View", url: "https://example.com" }],
    };
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("[View](https://example.com)");
  });

  it("uses <url|label> link format for Slack (contrast)", () => {
    const msg: RichMessage = {
      ...baseMsg,
      links: [{ label: "View", url: "https://example.com" }],
    };
    const result = richMessageToMarkdown(msg, "slack");
    expect(result).toContain("<https://example.com|View>");
  });

  it("field names use **bold** on Discord", () => {
    const msg: RichMessage = {
      ...baseMsg,
      fields: [{ name: "Status", value: "Active" }],
    };
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("**Status**");
    expect(result).toContain("Active");
  });

  it("multiple links joined with pipe separator", () => {
    const msg: RichMessage = {
      ...baseMsg,
      links: [
        { label: "Docs", url: "https://docs.example.com" },
        { label: "App", url: "https://app.example.com" },
      ],
    };
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("[Docs](https://docs.example.com)");
    expect(result).toContain("[App](https://app.example.com)");
    expect(result).toContain(" | ");
  });

  it("includes footer in italics", () => {
    const msg: RichMessage = {
      ...baseMsg,
      footer: "Powered by GAIA",
    };
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("_Powered by GAIA_");
  });

  it("includes author name when provided", () => {
    const msg: RichMessage = {
      ...baseMsg,
      authorName: "GAIA Bot",
    };
    const result = richMessageToMarkdown(msg, "discord");
    expect(result).toContain("GAIA Bot");
  });
});

// ---------------------------------------------------------------------------
// Slack link format (convertToSlackMrkdwn)
// The adapter calls convertToSlackMrkdwn on all text before sending.
// ---------------------------------------------------------------------------

import { convertToSlackMrkdwn } from "@gaia/shared";

describe("Slack-specific markdown conversion", () => {
  it("converts markdown links [label](url) to <url|label>", () => {
    const result = convertToSlackMrkdwn("[Click here](https://example.com)");
    expect(result).toBe("<https://example.com|Click here>");
  });

  it("preserves code blocks with Slack-style links inside", () => {
    const input = "```\n[label](url)\n```";
    const result = convertToSlackMrkdwn(input);
    expect(result).toContain("[label](url)");
    expect(result).not.toContain("<url|label>");
  });

  it("converts **bold** to *bold* (Slack mrkdwn)", () => {
    expect(convertToSlackMrkdwn("**important**")).toBe("*important*");
  });

  it("strips > blockquote prefix", () => {
    expect(convertToSlackMrkdwn("> quoted")).toBe("quoted");
  });

  it("removes horizontal rules", () => {
    expect(convertToSlackMrkdwn("---")).toBe("");
  });

  it("converts heading to *bold*", () => {
    expect(convertToSlackMrkdwn("# My Heading")).toBe("*My Heading*");
  });
});
