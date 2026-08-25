/**
 * Bubble segmentation for bot delivery.
 *
 * The model is told to split its replies with `<NEW_MESSAGE_BREAK>` and mostly
 * does not: across 42 consecutive production replies, ZERO carried an interior
 * sentinel, the median reply was 5 paragraphs delivered as one bubble, and the
 * worst was 21 paragraphs / 4,358 characters in a single Telegram message.
 * A bot has to segment deterministically rather than hope for the sentinel.
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
  it("splits prose on blank lines", () => {
    const bubbles = segmentIntoBubbles(
      "First paragraph, long enough to stand on its own as a bubble.\n\n" +
        "Second paragraph, also long enough to stand on its own here.",
    );

    expect(bubbles).toEqual([
      "First paragraph, long enough to stand on its own as a bubble.",
      "Second paragraph, also long enough to stand on its own here.",
    ]);
  });

  it("keeps a list whole even when its items are blank-line separated", () => {
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

  it("never splits inside a fenced code block", () => {
    const bubbles = segmentIntoBubbles(
      "Here is the migration you asked for, run it on staging first.\n\n" +
        "```python\ndef main():\n\n    print('hi')\n\n    return 0\n```\n\n" +
        "Then redeploy the worker so it picks the new schema up.",
    );

    const fenced = bubbles.filter((b) => b.includes("```"));
    expect(fenced).toHaveLength(1);
    expect(fenced[0].match(/```/g)).toHaveLength(2);
    expect(fenced[0]).toContain("print('hi')");
  });

  it("never splits a table away from its header", () => {
    const table =
      "| item | cost |\n|---|---|\n| resend | $20 |\n| domain | $12 |";
    const bubbles = segmentIntoBubbles(
      `Here is what the whole thing is going to cost you monthly.\n\n${table}`,
    );

    const withTable = bubbles.filter((b) => b.includes("| resend |"));
    expect(withTable).toHaveLength(1);
    expect(withTable[0]).toContain("|---|---|");
    expect(withTable[0]).toContain("| domain | $12 |");
  });

  it("keeps a heading with the block it introduces", () => {
    const bubbles = segmentIntoBubbles(
      "## What I set up\n\n- eight tasks in your Todoist inbox\n- two WhatsApp nudges",
    );

    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toContain("## What I set up");
    expect(bubbles[0]).toContain("two WhatsApp nudges");
  });

  it("keeps a lead-in line with the list it introduces", () => {
    const bubbles = segmentIntoBubbles(
      "**2 reminders, both on WhatsApp:**\n\n- 12pm today\n- 12am tonight",
    );

    expect(bubbles).toHaveLength(1);
  });

  it("merges a fragment too small to be its own message", () => {
    const bubbles = segmentIntoBubbles(
      "ok.\n\nHere is the actual answer, which is long enough to be a bubble.",
    );

    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toContain("ok.");
  });

  it("splits on the sentinel first, then paragraphs inside each segment", () => {
    const bubbles = segmentIntoBubbles(
      `Short intro that is long enough to survive on its own.${BREAK}` +
        "Second message paragraph one, long enough to stand alone.\n\n" +
        "Second message paragraph two, long enough to stand alone.",
    );

    expect(bubbles).toHaveLength(3);
    expect(bubbles[0]).toBe(
      "Short intro that is long enough to survive on its own.",
    );
  });

  it("drops a trailing partial sentinel instead of shipping it", () => {
    expect(segmentIntoBubbles("here are your numbers<NEW_MESSAGE_B")).toEqual([
      "here are your numbers",
    ]);
  });

  it("returns nothing for empty or sentinel-only text", () => {
    expect(segmentIntoBubbles("")).toEqual([]);
    expect(segmentIntoBubbles(`  ${BREAK}${BREAK} `)).toEqual([]);
  });

  it("breaks up the 21-paragraph production reply without losing a word", () => {
    const bubbles = segmentIntoBubbles(PROD_REPLY);

    // It arrived as ONE 4,358-character Telegram message.
    expect(bubbles.length).toBeGreaterThan(5);
    // And it must still read as a person texting, not a stutter.
    expect(bubbles.length).toBeLessThan(16);
    for (const bubble of bubbles) {
      expect(bubble.trim()).not.toBe("");
    }
    // The numbered lead-ins stay attached to the paragraph they introduce.
    const strandedHeading = bubbles.find((b) => /^\*\*\d\..*\*\*$/.test(b));
    expect(strandedHeading).toBeUndefined();
    // The closing action list survives as one block under its lead-in.
    const plan = bubbles.find((b) => b.includes("fix the checkout leak first"));
    expect(plan).toContain("only expand channels after");
    expect(plan).toContain("so the concrete play, in order:");
    // Nothing is dropped: every word of the source is delivered, in order.
    const words = (s: string) => s.split(/\s+/).filter(Boolean);
    expect(words(bubbles.join("\n\n"))).toEqual(
      words(PROD_REPLY.replaceAll(BREAK, " ")),
    );
  });
});
