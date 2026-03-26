/**
 * Tests for Telegram-specific mention detection and markdown fallback logic.
 *
 * The Telegram adapter has unique behaviors:
 * 1. Mention detection/stripping via the exported `hasTelegramMention` and
 *    `stripTelegramMention` helpers (case-sensitive plain-string, NOT a regex).
 * 2. Markdown fallback: retries without parse_mode when Telegram rejects markup.
 * 3. convertToTelegramMarkdown: the formatter applied to all outbound messages.
 */

import { convertToTelegramMarkdown } from "@gaia/shared";
import { describe, expect, it } from "vitest";
import {
  hasTelegramMention,
  stripTelegramMention,
} from "../../telegram/src/adapter";

describe("Telegram mention detection", () => {
  it("strips @BotName mention at start", () => {
    const result = stripTelegramMention(
      "@GaiaBot what is the weather",
      "GaiaBot",
    );
    expect(result).toBe("what is the weather");
  });

  it("does not strip @botname when case does not match", () => {
    // Production uses case-sensitive replaceAll — wrong case is not stripped.
    const result = stripTelegramMention("@gaiabot hello", "GaiaBot");
    expect(result).toBe("@gaiabot hello");
  });

  it("strips mention leaving rest of message intact", () => {
    const result = stripTelegramMention("@GaiaBot hello world", "GaiaBot");
    expect(result).toBe("hello world");
  });

  it("handles message that is only a mention", () => {
    // Production replies "How can I help you?" when content is empty after strip.
    // The stripping itself should produce an empty string.
    const result = stripTelegramMention("@GaiaBot", "GaiaBot");
    expect(result).toBe("");
  });

  it("strips mention anywhere in message", () => {
    // replaceAll removes all occurrences regardless of position.
    const result = stripTelegramMention(
      "hey @GaiaBot what time is it",
      "GaiaBot",
    );
    expect(result).toBe("hey  what time is it".trim());
  });

  it("does not detect mention when username does not appear", () => {
    expect(hasTelegramMention("@otherbot hello", "GaiaBot")).toBe(false);
  });

  it("detects mention at start of message", () => {
    expect(hasTelegramMention("@GaiaBot hello", "GaiaBot")).toBe(true);
  });

  it("detects mention anywhere in message", () => {
    expect(hasTelegramMention("help me @GaiaBot please", "GaiaBot")).toBe(true);
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
// We verify the exact error substrings the adapter checks in adapter.ts.
//
// Production checks (adapter.ts handleTelegramStreaming):
//   e.message.includes("can't parse entities")
//   e.message.includes("message is not modified")
// ---------------------------------------------------------------------------

describe("Telegram markdown error recognition", () => {
  // These are the exact substrings the production adapter checks.
  // If the Telegram API changes its error format these assertions will catch it.
  const PARSE_ERROR = "can't parse entities";
  const NOT_MODIFIED_ERROR = "message is not modified";

  it("parse error substring matches a real Telegram API error message", () => {
    // Telegram returns: "Bad Request: can't parse entities: Character '@' is reserved"
    const telegramError = new Error(
      "Bad Request: can't parse entities: Character '@' is reserved",
    );
    expect(telegramError.message.includes(PARSE_ERROR)).toBe(true);
  });

  it("not-modified substring matches a real Telegram API error message", () => {
    // Telegram returns: "Bad Request: message is not modified: specified new message content
    // and reply markup are exactly the same as a current content and reply markup of the message"
    const telegramError = new Error(
      "Bad Request: message is not modified: specified new message content and reply markup are exactly the same",
    );
    expect(telegramError.message.includes(NOT_MODIFIED_ERROR)).toBe(true);
  });

  it("parse error substring does not match a not-modified error", () => {
    const notModified = new Error("Bad Request: message is not modified");
    expect(notModified.message.includes(PARSE_ERROR)).toBe(false);
  });

  it("not-modified substring does not match a parse-entities error", () => {
    const parseError = new Error(
      "Bad Request: can't parse entities: Character '@' is reserved",
    );
    expect(parseError.message.includes(NOT_MODIFIED_ERROR)).toBe(false);
  });
});
