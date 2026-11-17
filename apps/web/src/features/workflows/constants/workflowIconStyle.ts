/**
 * Vibrant swatches computed in OKLCH (uniform lightness/chroma, evenly spaced
 * hues, gamut-mapped to sRGB) so every color reads equally bright on dark UI.
 */
export const WORKFLOW_ICON_COLORS = [
  "#ff726b", // coral
  "#f68001", // orange
  "#eebe0c", // gold
  "#5fbf49", // green
  "#0ebfa0", // teal
  "#09b7dc", // cyan
  "#72a3fe", // blue
  "#ad8dfe", // violet
  "#e175d9", // magenta
  "#fb6ca0", // pink
] as const;

export const DEFAULT_WORKFLOW_ICON_COLOR = WORKFLOW_ICON_COLORS[6]; // blue

/** Alpha suffix appended to a swatch hex for the icon's tinted background. */
export const WORKFLOW_ICON_BG_ALPHA = "26"; // ~15%

/** The size UnifiedWorkflowCard draws its custom icon at. */
export const WORKFLOW_CARD_ICON_SIZE = 25;

/** Server-rendered icons are keyed by slug and color, since the color is baked into the markup. */
export function workflowIconKey(
  icon: string,
  iconColor: string | null | undefined,
): string {
  return `${icon}|${iconColor ?? ""}`;
}
