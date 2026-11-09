import isUnicodeSupported from "is-unicode-supported";

/**
 * The accent colour: the terminal's own cyan, so every theme (light or dark)
 * picks a readable shade. The brand's truecolor blue is for the logo only.
 */
export const THEME_COLOR = "cyan";

/** A screen's lines sit this many columns in, under the header's. */
export const SCREEN_INDENT = 2;

/** Store key set when a process hands its screen to a docker-group relaunch. */
export const HANDED_OVER_KEY = "handedOver";

/** Maximum number of log lines retained per stream to limit memory usage */
export const LOG_BUFFER_LINES = 30;

/** The one border style every box uses. */
export const BOX_BORDER = "round";

const UNICODE = isUnicodeSupported();

/**
 * The status marks every screen and report uses. The mark carries the colour
 * (MARK_COLOR); the text beside it stays the default colour. Terminals that
 * cannot draw Unicode get ASCII stand-ins.
 */
export const MARK = {
  ok: UNICODE ? "✓" : "√",
  fail: UNICODE ? "✗" : "x",
  warn: "!",
  skip: UNICODE ? "–" : "-",
  pending: UNICODE ? "○" : "o",
  active: UNICODE ? "●" : "*",
  cancelled: UNICODE ? "■" : "#",
} as const;

export type MarkKind = keyof typeof MARK;

/** A progress bar's done and remaining runs. */
export const BAR = {
  done: UNICODE ? "━" : "=",
  rest: UNICODE ? "─" : "-",
} as const;

export const MARK_COLOR: Record<MarkKind, string> = {
  ok: "green",
  fail: "red",
  warn: "yellow",
  skip: "gray",
  pending: "gray",
  active: THEME_COLOR,
  cancelled: "yellow",
};
