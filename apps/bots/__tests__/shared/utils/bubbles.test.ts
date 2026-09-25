/**
 * Bubble segmentation for bot delivery.
 *
 * The model owns the splits via `<NEW_MESSAGE_BREAK>` (see Chat Bubbles in
 * the comms prompt): a reply with no sentinel ships as ONE bubble, and
 * nothing here invents blank-line splits. Blank lines are line breaks inside
 * a bubble, never boundaries.
 *
 * The web app splits on the sentinel alone and is deliberately untouched — this
 * is bot delivery only.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { segmentIntoBubbles } from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

const BREAK = "<NEW_MESSAGE_BREAK>";

const PROD_REPLY = readFileSync(
  join(__dirname, "__fixtures__", "long-prose-reply.txt"),
  "utf8",
);

describe("segmentIntoBubbles", () => {
  it("does not split on blank lines: no sentinel means one bubble", () => {
    const bubbles = segmentIntoBubbles(
      "First paragraph, long enough to stand on its own as a bubble.\n\n" +
        "Second paragraph, also long enough to stand on its own here.",
    );

    expect(bubbles).toEqual([
      "First paragraph, long enough to stand on its own as a bubble.\n\n" +
        "Second paragraph, also long enough to stand on its own here.",
    ]);
  });

  it("splits on the sentinel only, never further inside a segment", () => {
    const bubbles = segmentIntoBubbles(
      "Short intro that is long enough to survive on its own." +
        BREAK +
        "Second message paragraph one, long enough to stand alone.\n\n" +
        "Second message paragraph two, long enough to stand alone.",
    );

    expect(bubbles).toEqual([
      "Short intro that is long enough to survive on its own.",
      "Second message paragraph one, long enough to stand alone.\n\n" +
        "Second message paragraph two, long enough to stand alone.",
    ]);
  });

  it("keeps a blank-line-separated list whole without a sentinel", () => {
    const bubbles = segmentIntoBubbles(
      "- buy resend pro and set up the domain records\n\n" +
        "- email the churned subscribers with the new pricing\n\n" +
        "- email everyone who signed up and never paid us",
    );

    expect(bubbles).toHaveLength(1);
    expect(
      bubbles[0].split("\n").filter((l) => l.startsWith("-")),
    ).toHaveLength(3);
  });

  it("a sentinel inside a fenced code block does not split", () => {
    const bubbles = segmentIntoBubbles(
      "Run this migration on staging first:\n\n" +
        "```python\n" +
        `print('one')${BREAK}print('two')\n` +
        "```\n\n" +
        "Then redeploy the worker so it picks the new schema up.",
    );

    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).not.toContain(BREAK);
    expect(bubbles[0]).toContain("print('one')\nprint('two')");
  });

  it("keeps tables and headings whole without a sentinel", () => {
    const table =
      "| item | cost |\n|---|---|\n| resend | $20 |\n| domain | $12 |";
    const bubbles = segmentIntoBubbles(
      `## What this costs monthly\n\n${table}`,
    );

    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toContain("| resend |");
    expect(bubbles[0]).toContain("## What this costs");
  });

  it("drops a trailing partial sentinel instead of shipping it", () => {
    expect(segmentIntoBubbles("here are your numbers<NEW_MESSAGE_B")).toEqual([
      "here are your numbers",
    ]);
  });

  it("merges a fragment too small to be its own message", () => {
    const bubbles = segmentIntoBubbles(
      `ok.${BREAK}Here is the actual answer, which is long enough.`,
    );

    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toContain("ok.");
  });

  it("returns nothing for empty or sentinel-only text", () => {
    expect(segmentIntoBubbles("")).toEqual([]);
    expect(segmentIntoBubbles(`  ${BREAK}${BREAK} `)).toEqual([]);
  });

  it("ships a sentinel-free production reply as one bubble, word for word", () => {
    // Its only sentinels are a doubled token at the very end, an empty segment
    // that drops out; a forgotten token is fixed in the prompt, not here.
    const bubbles = segmentIntoBubbles(PROD_REPLY);

    expect(bubbles).toHaveLength(1);
    const words = (s: string) => s.split(/\s+/).filter(Boolean);
    expect(words(bubbles[0])).toEqual(words(PROD_REPLY.replaceAll(BREAK, " ")));
  });
});
