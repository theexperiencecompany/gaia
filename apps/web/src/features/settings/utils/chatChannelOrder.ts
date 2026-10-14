import type { NotificationPlatform } from "@/features/notification/constants";

/**
 * The order with the platform at `index` moved one place up or down.
 *
 * Returns the same array reference when the move would fall off either end, so
 * a caller can skip the save on a no-op instead of re-checking the bounds.
 */
export function moveChannel(
  order: NotificationPlatform[],
  index: number,
  direction: "up" | "down",
): NotificationPlatform[] {
  const target = direction === "up" ? index - 1 : index + 1;
  if (
    index < 0 ||
    index >= order.length ||
    target < 0 ||
    target >= order.length
  )
    return order;
  const next = [...order];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/**
 * The stored order restricted to the platforms the user has actually linked,
 * with any linked platform the stored order never mentioned appended.
 *
 * The settings list only offers platforms GAIA can really text on, but the
 * stored list is the full preference — so a newly linked platform has to appear
 * somewhere rather than vanish until the user reorders.
 */
export function linkedInPriorityOrder(
  order: NotificationPlatform[],
  linked: NotificationPlatform[],
): NotificationPlatform[] {
  const isLinked = new Set(linked);
  const inOrder = order.filter((platform) => isLinked.has(platform));
  const seen = new Set(inOrder);
  return [...inOrder, ...linked.filter((platform) => !seen.has(platform))];
}
