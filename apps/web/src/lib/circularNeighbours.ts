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
