import { describe, expect, it } from "vitest";
import {
  couldBecomeReactDirective,
  reactDirectiveEmoji,
} from "./react-directive";

// Same table as EMOJI_DIRECTIVE_CASES in apps/api/tests/unit/agents/test_comms_directive.py —
// change both together, or bots and backend disagree on what gets an emoji_ack.
const EMOJI_DIRECTIVE_CASES: readonly (readonly [string, string | null])[] = [
  ["<EMOJI>👍</EMOJI>", "👍"],
  ["  <emoji> ✅ </emoji>  ", "✅"],
  ["<EMOJI>👍</EMOJI>\n", "👍"],
  ["<EMOJI>😎</EMOJI><NEW_MESSAGE_BREAK>", "😎"],
  ["<EMOJI></EMOJI>", null],
  ["<EMOJI> </EMOJI><NEW_MESSAGE_BREAK>", null],
  ["<EMOJI>👍</SILENCE>", null],
  ["<EMOJI>👍", null],
  ["<EMOJI>👍</EMOJI>\nand more", null],
  ["<EMOJI>👍</EMOJI><NEW_MESSAGE_BREAK>and more", null],
  ["hello <EMOJI>👍</EMOJI>", null],
  // The pre-tag line format, still in comms' own history.
  ["REACT: 👍", "👍"],
  ["REACT: 😎<NEW_MESSAGE_BREAK>", "😎"],
  ["REACT: <NEW_MESSAGE_BREAK>", null],
  ["REACTION: completed", null],
  ["Booked your 9am flight to Tokyo.", null],
];

describe("reactDirectiveEmoji", () => {
  it.each(EMOJI_DIRECTIVE_CASES)("classifies %j as %j", (text, emoji) => {
    expect(reactDirectiveEmoji(text)).toBe(emoji);
  });
});

describe("couldBecomeReactDirective", () => {
  it.each(EMOJI_DIRECTIVE_CASES.filter(([, emoji]) => emoji !== null))(
    "holds the finished directive %j",
    (text) => {
      expect(couldBecomeReactDirective(text)).toBe(true);
    },
  );

  it.each([
    "",
    "  ",
    "<",
    "<em",
    "<EMOJI>",
    "<EMOJI>👍",
    "<EMOJI>👍</EMO",
    "REACT",
    "REACT: ",
  ])("holds %j, which one more frame can still make a directive", (text) => {
    expect(couldBecomeReactDirective(text)).toBe(true);
  });

  it.each([
    "Really interesting",
    "<b>bold</b> reply",
    "<EMOJI>👍</EMOJI>\nand more",
    "<EMOJI>\n",
    "hello <EMOJI>👍</EMOJI>",
    "<\nEMOJI>👍</EMOJI>",
    "REACTION: completed",
  ])("releases %j, which no later frame can make a directive", (text) => {
    expect(couldBecomeReactDirective(text)).toBe(false);
  });
});
