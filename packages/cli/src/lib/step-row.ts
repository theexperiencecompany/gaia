/**
 * The column widths of a step row: mark, label column, then the time
 * right-aligned in its own column. The Ink step list, the plain (non-TTY)
 * reporter and install.sh (its done_line and spin) draw rows to these widths,
 * so a run reads as one list.
 * @module lib/step-row
 */

export const LABEL_WIDTH = 36;
export const TIME_WIDTH = 8;
/** Spaces a label longer than the column still keeps before the timer. */
export const LABEL_GAP = 2;

/** The label padded to the column, never closer to the timer than LABEL_GAP. */
export function labelCell(label: string): string {
  return label.padEnd(Math.max(LABEL_WIDTH, label.length + LABEL_GAP));
}

/** "✓ Started GAIA                          1m 13s": a row as plain text, without the screen's indent. */
export function stepRowText(mark: string, label: string, time: string): string {
  return `${mark} ${labelCell(label)}${time.padStart(TIME_WIDTH)}`;
}
