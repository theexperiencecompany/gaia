/**
 * Lay a categorical palette out for react-ui's charts, which pick series colours centred on
 * the palette's middle (one series takes the middle, two take middle-1 and middle+1). Placing
 * the colours where that centring lands makes series 1 read the palette's first colour.
 */
export function orderedPalette(
  palette: readonly string[],
  seriesCount: number,
): string[] {
  const n = Math.max(1, seriesCount);
  const middle = n;
  const out = Array<string>(2 * n + 1).fill(palette[0]);
  const picks =
    n === 1
      ? [middle]
      : n === 2
        ? [middle - 1, middle + 1]
        : Array.from(
            { length: n },
            (_, i) => middle + (i - Math.floor((n - 1) / 2)),
          );
  picks.forEach((at, k) => {
    out[at] = palette[k % palette.length];
  });
  return out;
}
