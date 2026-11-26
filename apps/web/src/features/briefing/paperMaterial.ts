/**
 * The letter's paper: its grain, its unprinted back and the light on its edges,
 * each derived from the edition's own paper colour (a CSS colour) and whether
 * that paper is dark.
 */

/** Fine paper fibre: fractal noise, multiplied faintly over a face. */
export const PAPER_GRAIN = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.5 0 0 0 0 0.45 0 0 0 0 0.4 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E")`;

/** The reverse of a folded-under panel reads a touch cooler than its printed face. */
const REVERSE_TINT = "rgb(52, 64, 88)";

function mix(paper: string, share: number, toward: string): string {
  return `color-mix(in srgb, ${paper} ${share}%, ${toward})`;
}

/** A folded-under panel's unprinted reverse; `share` of the paper keeps, the rest cools. */
export function foldedReverse(paper: string, share: number): string {
  return mix(paper, share, REVERSE_TINT);
}

/** An unfolding panel's back: its own colour, shaded toward the crease it hangs from. */
export function panelBack(paper: string): string {
  return `linear-gradient(180deg, ${mix(paper, 80, "black")} 0%, ${mix(paper, 92, "black")} 45%, ${paper} 100%)`;
}

/** The front's bottom edge rolling under: a highlight on the curve, shading as it turns away. */
export function rolledEdge(paper: string, isDarkPaper: boolean): string {
  return `linear-gradient(180deg, ${paper} 0%, ${mix(paper, isDarkPaper ? 82 : 88, "white")} 30%, ${mix(paper, 78, "black")} 85%, ${mix(paper, 66, "black")} 100%)`;
}

/** The face bowing into its crease: the light falls off over the last stretch before the fold. */
export function creaseFalloff(isDarkPaper: boolean): string {
  return `linear-gradient(180deg, transparent 62%, rgba(0,0,0,${isDarkPaper ? 0.22 : 0.12}) 100%)`;
}

/** The front panel's shadow falling on the panels folded under it. */
export function underFoldShadow(isDarkPaper: boolean): string {
  return `linear-gradient(180deg, rgba(0,0,0,${isDarkPaper ? 0.5 : 0.32}) 0%, rgba(0,0,0,0.08) 55%, transparent 100%)`;
}

/** The light caught by a paper edge: the face's top, a folded panel's bottom. */
const EDGE_LIGHT = {
  face: { dark: "rgba(255,255,255,0.25)", light: "rgba(255,255,255,0.7)" },
  fold: { dark: "rgba(255,255,255,0.12)", light: "rgba(255,255,255,0.4)" },
} as const;

export function edgeLight(
  edge: keyof typeof EDGE_LIGHT,
  isDarkPaper: boolean,
): string {
  return EDGE_LIGHT[edge][isDarkPaper ? "dark" : "light"];
}
