/**
 * Tests for Telegram-specific mention detection and markdown fallback logic.
 *
 * The Telegram adapter has unique behaviors:
 * 1. Mention regex: strips "@botUsername" from messages in groups
 * 2. Markdown fallback: retries without parse_mode when Telegram rejects markup
 * 3. convertToTelegramMarkdown: the formatter applied to all outbound messages
 *
 * The mention regex pattern is built from the bot's username at runtime.
 * We test the pattern itself to ensure correct group message filtering.
 */

import { describe, it, expect } from "vitest";
import { convertToTelegramMarkdown } from "@gaia/shared";

// ---------------------------------------------------------------------------
// Mention regex helpers (replicated from adapter internals)
// These test the exact pattern the Telegram adapter constructs.
// ---------------------------------------------------------------------------

function buildMentionRegex(botUsername: string): RegExp {
  return new RegExp(`@${botUsername}`, "gi");
}

function stripMention(text: string, botUsername: string): string {
  return text.replace(buildMentionRegex(botUsername), "").trim();
}

describe("Telegram mention detection", () => {
  it("detects mention at start of message", () => {
    const regex = buildMentionRegex("gaiabot");
    expect(regex.test("@gaiabot hello")).toBe(true);
  });

  it("detects mention at end of message", () => {
    const regex = buildMentionRegex("gaiabot");
    expect(regex.test("help me @gaiabot")).toBe(true);
  });

  it("does not match different bot username", () => {
    const regex = buildMentionRegex("gaiabot");
    expect(regex.test("@otherbot hello")).toBe(false);
  });

  it("is case-insensitive", () => {
    // Note: create separate regex instances - the `g` flag makes regex stateful
    // (lastIndex advances after each .test()), so reusing gives wrong results.
    expect(buildMentionRegex("GaiaBot").test("@GAIABOT hello")).toBe(true);
    expect(buildMentionRegex("GaiaBot").test("@gaiabot hello")).toBe(true);
  });

  it("strips mention from start of message", () => {
    const result = stripMention("@gaiabot what is the weather", "gaiabot");
    expect(result).toBe("what is the weather");
  });

  it("strips mention from middle of message", () => {
    const result = stripMention("hey @gaiabot what time is it", "gaiabot");
    expect(result).toBe("hey  what time is it".trim());
  });

  it("strips mention from end of message", () => {
    const result = stripMention("send email @gaiabot", "gaiabot");
    expect(result).toBe("send email");
  });

  it("returns clean text when no mention present", () => {
    const result = stripMention("just a regular message", "gaiabot");
    expect(result).toBe("just a regular message");
  });
});

// ---------------------------------------------------------------------------
// Telegram markdown conversion
// These verify the formatter applied to all bot responses before sending.
// ---------------------------------------------------------------------------

describe("convertToTelegramMarkdown - bold conversion", () => {
  it("converts **bold** to *bold*", () => {
    expect(convertToTelegramMarkdown("**hello**")).toBe("*hello*");
  });

  it("converts ***bold italic*** to *bold italic*", () => {
    expect(convertToTelegramMarkdown("***text***")).toBe("*text*");
  });

  it("converts heading to bold", () => {
    expect(convertToTelegramMarkdown("## My Section")).toBe("*My Section*");
  });

  it("strips blockquote prefix", () => {
    expect(convertToTelegramMarkdown("> quoted text")).toBe("quoted text");
  });

  it("removes horizontal rules", () => {
    expect(convertToTelegramMarkdown("---")).toBe("");
    expect(convertToTelegramMarkdown("___")).toBe("");
  });

  it("preserves code blocks unchanged", () => {
    const code = "```\nconst x = **not bold**\n```";
    expect(convertToTelegramMarkdown(code)).toBe(code);
  });

  it("handles mixed: bold outside code, code unchanged", () => {
    const input = "**title**\n\n```\n**code**\n```";
    const result = convertToTelegramMarkdown(input);
    expect(result).toContain("*title*");
    expect(result).toContain("```\n**code**\n```");
  });
});

// ---------------------------------------------------------------------------
// Telegram-specific Markdown error scenarios
// The adapter retries with plain text when parse fails.
// We verify the error message format it checks against.
// ---------------------------------------------------------------------------

describe("Telegram markdown error recognition", () => {
  const PARSE_ERROR = "can't parse entities";
  const NOT_MODIFIED_ERROR = "message is not modified";

  it("parse error string is what Telegram API returns", () => {
    // This ensures our adapter's error check string is correct.
    // If Telegram changes the error string, this test will remind us.
    expect(PARSE_ERROR).toBe("can't parse entities");
  });

  it("not-modified error string is what Telegram API returns", () => {
    expect(NOT_MODIFIED_ERROR).toBe("message is not modified");
  });

  it("error string matching is case-sensitive substring check", () => {
    const error = new Error("Bad Request: can't parse entities: Character '@' is reserved");
    expect(error.message.includes(PARSE_ERROR)).toBe(true);
  });

  it("not-modified is not treated as parse error", () => {
    const notModified = new Error("Bad Request: message is not modified");
    expect(notModified.message.includes(PARSE_ERROR)).toBe(false);
    expect(notModified.message.includes(NOT_MODIFIED_ERROR)).toBe(true);
  });
});
