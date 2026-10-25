import { describe, expect, it } from "vitest";
import {
  type ColourEnvironment,
  colourLevel,
} from "../../src/lib/colour-level.js";

function level(
  env: NodeJS.ProcessEnv,
  overrides: Partial<ColourEnvironment> = {},
): number {
  return colourLevel({ env, isTTY: true, platform: "linux", ...overrides });
}

describe("colourLevel off switches", () => {
  it("is 0 when stdout is not a terminal, even on a truecolor terminal", () => {
    expect(
      level(
        { TERM: "xterm-256color", COLORTERM: "truecolor" },
        { isTTY: false },
      ),
    ).toBe(0);
  });

  it("is 0 under NO_COLOR", () => {
    expect(
      level({ TERM: "xterm-256color", COLORTERM: "truecolor", NO_COLOR: "1" }),
    ).toBe(0);
  });

  it("ignores an empty NO_COLOR, as no-color.org specifies", () => {
    expect(level({ TERM: "xterm-256color", NO_COLOR: "" })).toBe(3);
  });

  it("is 0 on TERM=dumb", () => {
    expect(level({ TERM: "dumb", COLORTERM: "truecolor" })).toBe(0);
  });

  it("is 0 on an unknown TERM", () => {
    expect(level({ TERM: "vt52" })).toBe(0);
  });

  it("is 0 with no TERM on a Unix terminal", () => {
    expect(level({})).toBe(0);
  });
});

describe("colourLevel FORCE_COLOR", () => {
  it.each([
    ["0", 0],
    ["false", 0],
    ["", 1],
    ["1", 1],
    ["true", 1],
    ["2", 2],
    ["3", 3],
  ])(
    "FORCE_COLOR=%j forces level %i, even off a terminal",
    (value, expected) => {
      expect(
        level({ TERM: "dumb", FORCE_COLOR: value }, { isTTY: false }),
      ).toBe(expected);
    },
  );

  it("refuses a FORCE_COLOR it cannot read rather than guess", () => {
    expect(() => level({ FORCE_COLOR: "4" })).toThrow(/FORCE_COLOR="4"/);
  });

  it("beats NO_COLOR, as in Node itself", () => {
    expect(level({ NO_COLOR: "1", FORCE_COLOR: "3" })).toBe(3);
  });
});

describe("colourLevel truecolor", () => {
  it.each(["truecolor", "24bit"])(
    "trusts COLORTERM=%s on any TERM",
    (value) => {
      expect(level({ TERM: "xterm", COLORTERM: value })).toBe(3);
    },
  );

  // An SSH session forwards TERM but neither COLORTERM nor TERM_PROGRAM.
  it.each([
    "xterm-256color",
    "rxvt-unicode-256color",
    "screen-256color",
    "tmux",
    "tmux-256color",
    "xterm-kitty",
    "xterm-ghostty",
    "alacritty",
    "wezterm",
    "foot",
    "foot-extra",
    "contour",
    "xterm-direct",
  ])("treats TERM=%s as truecolor without COLORTERM", (term) => {
    expect(level({ TERM: term })).toBe(3);
  });

  it.each(["iTerm.app", "WezTerm", "vscode", "ghostty"])(
    "treats TERM_PROGRAM=%s as truecolor",
    (program) => {
      expect(level({ TERM: "xterm", TERM_PROGRAM: program })).toBe(3);
    },
  );

  it("treats Windows Terminal as truecolor", () => {
    expect(level({ WT_SESSION: "abc" }, { platform: "win32" })).toBe(3);
  });

  it("treats a Windows console without TERM as truecolor", () => {
    expect(level({}, { platform: "win32" })).toBe(3);
  });
});

describe("colourLevel limited terminals", () => {
  it("keeps Apple Terminal at 256 colours despite its xterm-256color TERM", () => {
    expect(
      level({ TERM: "xterm-256color", TERM_PROGRAM: "Apple_Terminal" }),
    ).toBe(2);
  });

  it("trusts COLORTERM over Apple Terminal's default", () => {
    expect(
      level({
        TERM: "xterm-256color",
        TERM_PROGRAM: "Apple_Terminal",
        COLORTERM: "truecolor",
      }),
    ).toBe(3);
  });

  it.each([
    "linux",
    "xterm",
    "screen",
    "vt100",
    "rxvt",
    "ansi",
    "cygwin",
    "xterm-color",
  ])("keeps TERM=%s at 16 colours", (term) => {
    expect(level({ TERM: term })).toBe(1);
  });

  it("lifts an unknown TERM to 16 colours when COLORTERM says it has colour", () => {
    expect(level({ TERM: "vt52", COLORTERM: "yes" })).toBe(1);
  });
});
