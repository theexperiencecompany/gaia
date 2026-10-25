import wrapAnsi from "wrap-ansi";

/** Below this many columns, wrapping makes text harder to read, not easier. */
const MIN_WRAP_COLUMNS = 40;

/** Size assumed when a stream reports none (0 on a sizeless pty). */
const DEFAULT_COLUMNS = 80;
const DEFAULT_ROWS = 24;

export interface TerminalSize {
  columns: number;
  rows: number;
}

/** A stream's size, or 80x24 when it reports none. */
export function terminalSize(stream: NodeJS.WriteStream): TerminalSize {
  return {
    columns: stream.columns || DEFAULT_COLUMNS,
    rows: stream.rows || DEFAULT_ROWS,
  };
}

/**
 * Wrap at spaces to width, never starting a line with one. Ink's own wrap
 * keeps the space when a word ends exactly at the edge, so Ink text whose
 * width is known is wrapped here first.
 */
export function wrapToWidth(text: string, width: number): string {
  return wrapAnsi(text, width, { hard: true });
}

/**
 * Wrap text to the terminal so continuation lines start at `indent` columns;
 * output to a pipe is left unwrapped for whoever reads it next.
 */
export function wrapForTerminal(text: string, indent = 0): string {
  const columns = process.stdout.isTTY ? process.stdout.columns : undefined;
  if (!columns || columns - indent < MIN_WRAP_COLUMNS) return text;
  return wrapToWidth(text, columns - indent)
    .split("\n")
    .join(`\n${" ".repeat(indent)}`);
}
