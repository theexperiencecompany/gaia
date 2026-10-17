export const THEME_COLOR = "#00bbff";

/** Maximum number of log lines retained per stream to limit memory usage */
export const LOG_BUFFER_LINES = 30;

/** The one border style every box uses. */
export const BOX_BORDER = "round";

/**
 * The status marks every screen and report uses, with the colour each means:
 * ok green, problem red, warning yellow, skipped/not checked gray.
 */
export const MARK = {
  ok: "✓",
  fail: "✗",
  warn: "!",
  skip: "–",
} as const;

export type MarkKind = keyof typeof MARK;

export const MARK_COLOR: Record<MarkKind, string> = {
  ok: "green",
  fail: "red",
  warn: "yellow",
  skip: "gray",
};
