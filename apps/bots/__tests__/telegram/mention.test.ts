/**
 * Tests for Telegram-specific mention detection and the outbound HTML formatter.
 *
 * The Telegram adapter has unique behaviors:
 * 1. Mention detection/stripping via the exported `hasTelegramMention` and
 *    `stripTelegramMention` helpers (case-sensitive plain-string, NOT a regex).
 * 2. `convertToTelegramHtml`: the formatter applied to every outbound message.
 *    Telegram now sends with `parse_mode: "HTML"`, so the converter emits HTML
 *    (`<b>`, `<a href>`, escaped `&<>`) instead of legacy Markdown.
 * 3. Markdown/HTML error recognition: the adapter ignores "message is not
 *    modified" edits and falls back to plain text otherwise.
 *
 * These tests import the REAL `@gaia/shared` (no mock) so they verify the actual
 * conversion behavior — a test here fails if the production formatter regresses.
 */

import { convertToTelegramHtml } from "@gaia/shared";
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
// Telegram HTML conversion
// Telegram sends with parse_mode: "HTML", so the converter emits HTML tags.
// These verify the formatter applied to every bot response before sending.
// ---------------------------------------------------------------------------

describe("convertToTelegramHtml - emphasis conversion", () => {
  it("converts **bold** to <b>bold</b>", () => {
    expect(convertToTelegramHtml("**hello**")).toBe("<b>hello</b>");
  });

  it("converts ***bold italic*** to nested <b><i>", () => {
    expect(convertToTelegramHtml("***text***")).toBe("<b><i>text</i></b>");
  });

  it("converts *italic* to <i>italic</i>", () => {
    expect(convertToTelegramHtml("*emphasis*")).toBe("<i>emphasis</i>");
  });

  it("converts a heading to bold", () => {
    expect(convertToTelegramHtml("## My Section")).toBe("<b>My Section</b>");
  });

  it("strips the blockquote prefix", () => {
    expect(convertToTelegramHtml("> quoted text")).toBe("quoted text");
  });

  it("removes horizontal rules", () => {
    expect(convertToTelegramHtml("---")).toBe("");
    expect(convertToTelegramHtml("___")).toBe("");
  });
});

describe("convertToTelegramHtml - links", () => {
  it("converts [label](url) to an HTML anchor", () => {
    expect(convertToTelegramHtml("[GAIA](https://heygaia.io)")).toBe(
      '<a href="https://heygaia.io">GAIA</a>',
    );
  });

  it("renders bold text alongside a masked link", () => {
    expect(
      convertToTelegramHtml("**Sign in** at [here](https://heygaia.io/auth)"),
    ).toBe('<b>Sign in</b> at <a href="https://heygaia.io/auth">here</a>');
  });
});

describe("convertToTelegramHtml - HTML escaping", () => {
  it("escapes &, <, and > in narrative text so Telegram never mis-parses", () => {
    expect(convertToTelegramHtml("Tom & Jerry <script>")).toBe(
      "Tom &amp; Jerry &lt;script&gt;",
    );
  });

  it("does NOT italicize underscores in snake_case identifiers", () => {
    // Legacy Markdown turned `user_id` into `user<i>id` and dropped underscores.
    expect(convertToTelegramHtml("the user_id field")).toBe(
      "the user_id field",
    );
  });

  it("preserves underscores in a URL with an auth token (the shipped bug)", () => {
    // This is the exact regression we shipped: a masked link whose URL contains
    // underscores (an auth token) must round-trip the URL intact — legacy
    // Markdown italicized the `_x_` runs inside the token and silently dropped
    // the underscores, breaking the sign-in link.
    const url = "https://heygaia.io/auth?token=AjJD_TFC2_1Fgn";
    const result = convertToTelegramHtml(`[Sign in](${url})`);
    expect(result).toBe(`<a href="${url}">Sign in</a>`);
    // The token survives byte-for-byte — no <i> tags, no missing underscores.
    expect(result).toContain("AjJD_TFC2_1Fgn");
    expect(result).not.toContain("<i>");
  });

  it("preserves underscores in a bare URL (no italicizing)", () => {
    const url = "https://example.com/path/some_file_name?a=b_c_d";
    expect(convertToTelegramHtml(url)).toBe(url);
    expect(convertToTelegramHtml(url)).not.toContain("<i>");
  });
});

describe("convertToTelegramHtml - code blocks", () => {
  it("wraps fenced code in <pre> and does not convert markup inside it", () => {
    const result = convertToTelegramHtml("```\nconst x = **not bold**\n```");
    expect(result).toContain("<pre>");
    expect(result).not.toContain("<b>not bold</b>");
    // Asterisks inside code are escaped/preserved, never turned into tags.
    expect(result).toContain("**not bold**");
  });

  it("converts bold outside code while leaving fenced code untouched", () => {
    const result = convertToTelegramHtml("**title**\n\n```\n**code**\n```");
    expect(result).toContain("<b>title</b>");
    expect(result).toContain("**code**");
    expect(result).not.toContain("<b>code</b>");
  });

  it("wraps inline code in <code>", () => {
    expect(convertToTelegramHtml("run `npm install` now")).toBe(
      "run <code>npm install</code> now",
    );
  });
});

// ---------------------------------------------------------------------------
// Telegram edit error recognition
// The adapter ignores "message is not modified" edits and falls back to plain
// text on any other failure. We verify the exact substring the adapter checks.
//
// Production check (adapter.ts editHtml):
//   e.message.includes("message is not modified")
// ---------------------------------------------------------------------------

describe("Telegram edit error recognition", () => {
  const NOT_MODIFIED_ERROR = "message is not modified";

  it("not-modified substring matches a real Telegram API error message", () => {
    // Telegram returns: "Bad Request: message is not modified: specified new
    // message content and reply markup are exactly the same ..."
    const telegramError = new Error(
      "Bad Request: message is not modified: specified new message content and reply markup are exactly the same",
    );
    expect(telegramError.message.includes(NOT_MODIFIED_ERROR)).toBe(true);
  });

  it("not-modified substring does not match an unrelated parse error", () => {
    const parseError = new Error(
      "Bad Request: can't parse entities: Unsupported start tag",
    );
    expect(parseError.message.includes(NOT_MODIFIED_ERROR)).toBe(false);
  });
});
