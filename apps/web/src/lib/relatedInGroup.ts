import { circularNeighbours } from "@/lib/circularNeighbours";

const RING_OFFSETS = [1, 2, 3] as const;

/** Up to three same-group siblings after this item in slug order, wrapping, so every item is suggested by its predecessors. */
export function relatedInGroup<T extends { readonly slug: string }>(
  items: readonly T[],
  slug: string,
  groupOf: (item: T) => string,
): T[] {
  const current = items.find((item) => item.slug === slug);
  if (!current) return [];
  const group = groupOf(current);
  const ring = items
    .filter((item) => groupOf(item) === group)
    .toSorted((a, b) => a.slug.localeCompare(b.slug));
  const neighbours = circularNeighbours(
    ring,
    ring.indexOf(current),
    RING_OFFSETS,
  );
  return [...new Set(neighbours)];
}
