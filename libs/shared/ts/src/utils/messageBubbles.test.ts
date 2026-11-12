import { describe, expect, it } from "vitest";
import { NEW_MESSAGE_BREAK_TOKEN as BREAK } from "./messageBreakUtils";
import { splitMessageByBreaks, splitStreamingBubbles } from "./messageBubbles";

const CODE = "```python\nprint('hi')\nprint('there')\n```";

describe("splitMessageByBreaks", () => {
  it.each<[string, string, string[]]>([
    [
      "R1 one bubble",
      "Done, your reminder is set.",
      ["Done, your reminder is set."],
    ],
    [
      "R2 three bubbles",
      `Morning!${BREAK}Three meetings today.${BREAK}Move the standup?`,
      ["Morning!", "Three meetings today.", "Move the standup?"],
    ],
    ["R6 a leading break", `${BREAK}Hello there.`, ["Hello there."]],
    ["R6 a trailing break", `Hello there.${BREAK}`, ["Hello there."]],
    ["R6 two breaks in a row", `One.${BREAK}${BREAK}Two.`, ["One.", "Two."]],
    ["R6 only breaks", `${BREAK} ${BREAK}`, []],
    [
      "R7 a break inside a code fence stays in the code",
      `Here.\n\n\`\`\`python\nprint('hi')\n${BREAK}\nprint('there')\n\`\`\`${BREAK}Tell me.`,
      ["Here.\n\n```python\nprint('hi')\n\n\nprint('there')\n```", "Tell me."],
    ],
    [
      "R7 a break inside an openui block stays in the block",
      `Look:\n:::openui\nCard(a)${BREAK}Card(b)\n:::${BREAK}Done.`,
      ["Look:\n:::openui\nCard(a)\nCard(b)\n:::", "Done."],
    ],
    [
      "R8 a link-only bubble stays alone however short",
      `Here it is.${BREAK}https://github.com/x/y${BREAK}See the readme.`,
      ["Here it is.", "https://github.com/x/y", "See the readme."],
    ],
    [
      "short bubbles are the model's to make, never merged",
      `haha${BREAK}that's wild`,
      ["haha", "that's wild"],
    ],
    [
      "every sentinel spelling splits",
      "a[NEW_MESSAGE_BREAK]b</NEW_MESSAGE_BREAK>c<NEW_LINE_BREAK>d<new message break>e",
      ["a", "b", "c", "d", "e"],
    ],
    [
      "a reply cut off mid-sentinel",
      "here are your numbers<NEW_MESSAGE_B",
      ["here are your numbers"],
    ],
  ])("%s", (_name, text, expected) => {
    expect(splitMessageByBreaks(text)).toEqual(expected);
  });
});

const R2 = `Morning! Here is your day.${BREAK}Three meetings, first at ten.${BREAK}Move the standup?`;
const R7 = `Here is the script.\n\n${CODE}${BREAK}Tell me if it breaks.`;

/** Every prefix of `text`: what a client holds after each received character. */
function prefixes(text: string): string[] {
  return Array.from({ length: text.length + 1 }, (_, i) => text.slice(0, i));
}

describe("splitStreamingBubbles", () => {
  it.each([
    ["R2", R2],
    ["R4 every split point of a break", `First bubble.${BREAK}Second bubble.`],
    ["R6", `${BREAK}One.${BREAK}${BREAK}Two.${BREAK}`],
    ["R7", R7],
    ["variant spelling", "First.[NEW_LINE_BREAK]Second."],
  ])(
    "%s: never shows a sentinel, whole or partial, at any split point",
    (_name, text) => {
      for (const prefix of prefixes(text)) {
        const { complete, open } = splitStreamingBubbles(prefix);
        for (const bubble of [...complete, open]) {
          expect(bubble).not.toMatch(/[<[]\s*\/?\s*N(E(W)?)?/i);
        }
      }
    },
  );

  it.each([
    ["R2", R2],
    ["R4", `First bubble.${BREAK}Second bubble.`],
    ["R6", `${BREAK}One.${BREAK}${BREAK}Two.${BREAK}`],
    ["R7", R7],
  ])(
    "%s: a sealed bubble never changes and the bubbles only grow",
    (_name, text) => {
      let previous = splitStreamingBubbles("");
      for (const prefix of prefixes(text)) {
        const next = splitStreamingBubbles(prefix);
        expect(next.complete.slice(0, previous.complete.length)).toEqual(
          previous.complete,
        );
        if (next.complete.length === previous.complete.length) {
          expect(next.open.startsWith(previous.open.trimEnd())).toBe(true);
        } else {
          expect(
            next.complete[previous.complete.length]?.startsWith(
              previous.open.trimEnd(),
            ),
          ).toBe(true);
        }
        previous = next;
      }
    },
  );

  it("ends as the finished reply's bubbles", () => {
    for (const text of [R2, R7, `${BREAK}One.${BREAK}${BREAK}Two.${BREAK}`]) {
      const { complete, open } = splitStreamingBubbles(text);
      expect([...complete, open].filter(Boolean)).toEqual(
        splitMessageByBreaks(text),
      );
    }
  });

  it("holds the open bubble apart from the sealed ones", () => {
    expect(splitStreamingBubbles(`One.${BREAK}Tw`)).toEqual({
      complete: ["One."],
      open: "Tw",
    });
    expect(splitStreamingBubbles(`One.${BREAK}`)).toEqual({
      complete: ["One."],
      open: "",
    });
    expect(splitStreamingBubbles("One.<NEW_MES")).toEqual({
      complete: [],
      open: "One.",
    });
  });
});
