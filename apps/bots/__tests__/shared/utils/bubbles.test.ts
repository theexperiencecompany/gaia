/**
 * The messages a bot sends for one finished reply: the model's bubbles, each
 * cut to the platform's limit. A reply with no sentinel is ONE bubble; blank
 * lines are line breaks inside it, never boundaries.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  deliverableBubbles,
  PLATFORM_LIMITS,
  PLATFORM_MARKDOWN,
  type PlatformName,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

const BREAK = "<NEW_MESSAGE_BREAK>";

const PROD_REPLY = readFileSync(
  join(__dirname, "__fixtures__", "long-prose-reply.txt"),
  "utf8",
);

const bubblesOf = (text: string, platform: PlatformName = "telegram") =>
  deliverableBubbles(text, platform, PLATFORM_MARKDOWN[platform]);

describe("deliverableBubbles", () => {
  it("does not split on blank lines: no sentinel means one bubble", () => {
    const text =
      "First paragraph, long enough to stand on its own as a bubble.\n\n" +
      "Second paragraph, also long enough to stand on its own here.";

    expect(bubblesOf(text)).toEqual([[text]]);
  });

  it("keeps a blank-line-separated list, a table and a heading whole", () => {
    const table =
      "| item | cost |\n|---|---|\n| resend | $20 |\n| domain | $12 |";
    const text = `## What this costs monthly\n\n${table}\n\n- one\n\n- two`;

    expect(bubblesOf(text)).toEqual([[text]]);
  });

  it("keeps the model's short bubbles and a link-only bubble apart", () => {
    expect(
      bubblesOf(`ok.${BREAK}https://github.com/x/y${BREAK}See the readme.`),
    ).toEqual([["ok."], ["https://github.com/x/y"], ["See the readme."]]);
  });

  it.each<PlatformName>(["discord", "slack", "telegram"])(
    "cuts a bubble longer than %s allows into several messages of that bubble",
    (platform) => {
      const long = "A sentence of a long plan that ends cleanly. ".repeat(200);
      const [intro, chunks] = bubblesOf(`Intro.${BREAK}${long}`, platform);

      expect(intro).toEqual(["Intro."]);
      expect(chunks?.length).toBeGreaterThan(1);
      for (const chunk of chunks ?? []) {
        expect(PLATFORM_MARKDOWN[platform](chunk).length).toBeLessThanOrEqual(
          PLATFORM_LIMITS[platform],
        );
      }
    },
  );

  it("ships a sentinel-free production reply as one bubble, word for word", () => {
    // Its only sentinels are a doubled token at the very end, an empty segment
    // that drops out; a forgotten token is fixed in the prompt, not here.
    const bubbles = bubblesOf(PROD_REPLY);

    expect(bubbles).toHaveLength(1);
    const words = (s: string) => s.split(/\s+/).filter(Boolean);
    expect(words((bubbles[0] ?? []).join(" "))).toEqual(
      words(PROD_REPLY.replaceAll(BREAK, " ")),
    );
  });
});
