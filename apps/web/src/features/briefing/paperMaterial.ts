/** The letter's paper: its unprinted back, derived from the edition's own paper colour (a CSS colour). */

function mix(paper: string, share: number, toward: string): string {
  return `color-mix(in srgb, ${paper} ${share}%, ${toward})`;
}

/** An unfolding panel's back: its own colour, shaded toward the crease it hangs from. */
export function panelBack(paper: string): string {
  return `linear-gradient(180deg, ${mix(paper, 80, "black")} 0%, ${mix(paper, 92, "black")} 45%, ${paper} 100%)`;
}
