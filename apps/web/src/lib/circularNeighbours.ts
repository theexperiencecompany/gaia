/** The items at the given offsets from one item, wrapping at the ends: with the same offsets for every item, each is linked from as many siblings as it links. */
export function circularNeighbours<T>(
  items: readonly T[],
  index: number,
  offsets: readonly number[],
): T[] {
  if (index < 0 || items.length < 2) return [];
  return offsets.flatMap((offset) => {
    const neighbour = items[(index + offset + items.length * 2) % items.length];
    return neighbour === undefined || neighbour === items[index]
      ? []
      : [neighbour];
  });
}

/** Every other item, starting after the one at `index` and wrapping round; all of them when `index` is -1. */
export function itemsAfter<T>(items: readonly T[], index: number): T[] {
  return [...items.slice(index + 1), ...items.slice(0, Math.max(index, 0))];
}
