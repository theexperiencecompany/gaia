import { describe, it, expect } from "vitest";
import { parseTextArgs, truncateResponse } from "@gaia/shared";

// ---------------------------------------------------------------------------
// parseTextArgs
// ---------------------------------------------------------------------------
describe("parseTextArgs", () => {
  it("parses single word as subcommand with empty args", () => {
    const result = parseTextArgs("list");
    expect(result).toEqual({ subcommand: "list", args: [] });
  });

  it("parses multiple words: first is subcommand, rest are args", () => {
    const result = parseTextArgs("add Buy milk today");
    expect(result).toEqual({
      subcommand: "add",
      args: ["Buy", "milk", "today"],
    });
  });

  it('defaults to "list" for empty string', () => {
    const result = parseTextArgs("");
    expect(result).toEqual({ subcommand: "list", args: [] });
  });

  it("skips first token when skipFirst is true", () => {
    const result = parseTextArgs("/todo add something", true);
    expect(result).toEqual({ subcommand: "add", args: ["something"] });
  });

  it("trims extra whitespace", () => {
    const result = parseTextArgs("  get   wf-123  ");
    expect(result).toEqual({ subcommand: "get", args: ["wf-123"] });
  });
});

// ---------------------------------------------------------------------------
// truncateResponse
// ---------------------------------------------------------------------------
describe("truncateResponse", () => {
  it("returns short text unchanged for discord", () => {
    expect(truncateResponse("hello", "discord")).toBe("hello");
  });

  it("returns short text unchanged for slack", () => {
    expect(truncateResponse("hello", "slack")).toBe("hello");
  });

  it("returns short text unchanged for telegram", () => {
    expect(truncateResponse("hello", "telegram")).toBe("hello");
  });

  it("truncates at Discord limit (2000 chars)", () => {
    const long = "a ".repeat(1500); // 3000 chars
    const result = truncateResponse(long, "discord");
    expect(result.length).toBeLessThanOrEqual(2000);
  });

  it("truncates at Slack limit (4000 chars)", () => {
    const long = "word ".repeat(1000); // 5000 chars
    const result = truncateResponse(long, "slack");
    expect(result.length).toBeLessThanOrEqual(4000);
  });

  it("truncates at Telegram limit (4096 chars)", () => {
    const long = "word ".repeat(1100); // 5500 chars
    const result = truncateResponse(long, "telegram");
    expect(result.length).toBeLessThanOrEqual(4096);
  });

  it("truncates at word boundary", () => {
    // Build text that is over the discord limit with clear word boundaries
    const long = "abcdefghij ".repeat(200); // 2200 chars
    const result = truncateResponse(long, "discord");
    // The main content (before the suffix) should end at a space boundary,
    // meaning it should not cut mid-word. Since words are "abcdefghij",
    // the content should end with a complete word followed by nothing partial.
    const mainContent = result.replace(/\n\n\.\.\. \(truncated\)$/, "");
    // Verify it ends with a complete "abcdefghij" word, not a partial one
    expect(mainContent.trimEnd()).toMatch(/abcdefghij$/);
  });

  it('appends "... (truncated)" when no URL provided', () => {
    const long = "x ".repeat(1500);
    const result = truncateResponse(long, "discord");
    expect(result).toContain("... (truncated)");
  });

  it("appends conversation URL when provided", () => {
    const long = "x ".repeat(1500);
    const url = "https://app.gaia.com/c/123";
    const result = truncateResponse(long, "discord", url);
    expect(result).toContain("[View full response]");
    expect(result).toContain(url);
    expect(result).not.toContain("(truncated)");
  });

  it("does not cut inside markdown links", () => {
    // Craft text so the link straddles the truncation boundary
    const padding = "x ".repeat(950); // ~1900 chars
    const textWithLink = `${padding}[Click here for more information](https://example.com/very/long/path)`;
    const result = truncateResponse(textWithLink, "discord");
    // Should not contain an incomplete markdown link
    const openBrackets = (result.match(/\[/g) || []).length;
    const closeBrackets = (result.match(/\]/g) || []).length;
    // Either the link is fully included or fully excluded
    expect(openBrackets).toBe(closeBrackets);
  });
});
