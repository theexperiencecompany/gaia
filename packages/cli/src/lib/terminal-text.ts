import wrapAnsi from "wrap-ansi";

/** Below this many columns, wrapping makes text harder to read, not easier. */
const MIN_WRAP_COLUMNS = 40;

/**
 * Wrap text to the terminal so continuation lines start at `indent` columns;
 * output to a pipe is left unwrapped for whoever reads it next.
 */
export function wrapForTerminal(text: string, indent = 0): string {
  const columns = process.stdout.isTTY ? process.stdout.columns : undefined;
  if (!columns || columns - indent < MIN_WRAP_COLUMNS) return text;
  return wrapAnsi(text, columns - indent, { hard: true })
    .split("\n")
    .join(`\n${" ".repeat(indent)}`);
}
