import { describe, expect, it } from "vitest";
import {
  displaySafeStreamText,
  NEW_MESSAGE_BREAK_TOKEN,
  splitMessageByBreaks,
  trailingPartialBreakLength,
} from "./messageBreakUtils";

describe("trailingPartialBreakLength", () => {
  it("returns the length of a half-arrived break token at the tail", () => {
    // "<NEW_MESSAGE_B" is 14 chars and a prefix of the 19-char token.
    expect(trailingPartialBreakLength("now<NEW_MESSAGE_B")).toBe(14);
    expect(trailingPartialBreakLength("done<")).toBe(1);
    expect(trailingPartialBreakLength("x<NEW_MESSAGE_BREAK")).toBe(18);
  });

  it("returns 0 when the tail cannot start a break token", () => {
    expect(trailingPartialBreakLength("plain text")).toBe(0);
    expect(trailingPartialBreakLength("")).toBe(0);
    expect(trailingPartialBreakLength("ends with >")).toBe(0);
  });

  it("never reports a complete token as partial", () => {
    // A whole token is handled by splitting, not withholding.
    expect(trailingPartialBreakLength(`a${NEW_MESSAGE_BREAK_TOKEN}`)).toBe(0);
  });
});

describe("displaySafeStreamText", () => {
  it("withholds a partial break token split across stream chunks", () => {
    // The exact production bug: `...now<NEW_MESSAGE_B` leaked into a Telegram bubble.
    expect(displaySafeStreamText("handing over now<NEW_MESSAGE_B")).toBe(
      "handing over now",
    );
    expect(displaySafeStreamText("done<NEW_MESSAGE")).toBe("done");
  });

  it("strips complete break tokens for single-bubble display", () => {
    expect(displaySafeStreamText(`hello${NEW_MESSAGE_BREAK_TOKEN}world`)).toBe(
      "helloworld",
    );
  });

  it("strips a complete token and withholds a following partial one", () => {
    expect(displaySafeStreamText(`a${NEW_MESSAGE_BREAK_TOKEN}b<NEW_ME`)).toBe(
      "ab",
    );
  });

  it("passes ordinary text through untouched", () => {
    expect(displaySafeStreamText("just a normal reply")).toBe(
      "just a normal reply",
    );
  });
});

describe("splitMessageByBreaks", () => {
  it("splits on the break token and trims empties", () => {
    expect(
      splitMessageByBreaks(`first${NEW_MESSAGE_BREAK_TOKEN} second `),
    ).toEqual(["first", "second"]);
  });

  it("returns a single segment when there is no break", () => {
    expect(splitMessageByBreaks("no breaks here")).toEqual(["no breaks here"]);
  });
});
