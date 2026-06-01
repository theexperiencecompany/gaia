import {
  chunkResponse,
  parseTextArgs,
  renderForPlatform,
  truncateResponse,
} from "@gaia/shared";
import { describe, expect, it } from "vitest";

/** A wide GFM table — renders to a Telegram <pre> block whose column padding
 *  and ─ rule line make the visible output longer than the raw markdown. */
const WIDE_TABLE = [
  `| ${Array.from({ length: 6 }, (_, i) => `c${i}`.padEnd(40, "x")).join(" | ")} |`,
  `|${"---|".repeat(6)}`,
  `| ${Array.from({ length: 6 }, (_, i) => `v${i}`.padEnd(40, "y")).join(" | ")} |`,
].join("\n");

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

  it("truncates at Slack limit (3000 chars)", () => {
    const long = "word ".repeat(1000); // 5000 chars
    const result = truncateResponse(long, "slack");
    expect(result.length).toBeLessThanOrEqual(3000);
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

describe("chunkResponse", () => {
  it("returns the text unchanged when it already fits", () => {
    expect(chunkResponse("short message", "telegram")).toEqual([
      "short message",
    ]);
  });

  it("splits over-limit text into in-order pieces that reconstruct the original", () => {
    const text = "word ".repeat(1000); // 5000 chars, > telegram 4096
    const chunks = chunkResponse(text, "telegram");
    expect(chunks.length).toBeGreaterThan(1);
    // No information is lost across the split (whitespace at cut points aside).
    expect(chunks.join(" ").replace(/\s+/g, " ").trim()).toBe(text.trim());
  });

  it("keeps each RENDERED chunk within the platform limit when a renderer is given", () => {
    // Many wide tables: chunking by RAW length packs ~4096 chars per chunk, but
    // the Telegram renderer pads tables into <pre> blocks that overflow 4096.
    const text = `${WIDE_TABLE}\n\n`.repeat(40);
    const render = (c: string) => renderForPlatform(c, "telegram");

    const chunks = chunkResponse(text, "telegram", render);
    for (const chunk of chunks) {
      expect(render(chunk).length).toBeLessThanOrEqual(4096);
    }

    // The renderer-aware shrink is doing real work: raw-only chunking (no
    // renderer) WOULD emit a chunk that overflows once rendered. If this is
    // ever false the test above would pass vacuously.
    const rawChunks = chunkResponse(text, "telegram");
    expect(rawChunks.some((c) => render(c).length > 4096)).toBe(true);
  });

  it("never splits a GFM table across chunks", () => {
    // Place a table so it straddles Discord's 2000-char cut window.
    const filler = `${"sentence words here. ".repeat(95)}\n\n`; // ~1900 chars
    const text = `${filler}${WIDE_TABLE}\n\ntail text after the table`;

    const chunks = chunkResponse(text, "discord");

    expect(chunks.length).toBeGreaterThan(1);
    // Exactly one chunk contains the whole table block, contiguous and intact.
    const withTable = chunks.filter((c) => c.includes(WIDE_TABLE));
    expect(withTable).toHaveLength(1);
  });
});
