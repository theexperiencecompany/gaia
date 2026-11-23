import type { NotificationPlatform } from "@/features/notification/constants";

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

/**
 * The full stored order with `first` at the front of the linked platforms.
 *
 * Unlinked platforms keep their place at the tail, so relinking one later
 * restores the position the user chose for it.
 */
export function withChannelFirst(
  order: NotificationPlatform[],
  linked: NotificationPlatform[],
  first: NotificationPlatform,
): NotificationPlatform[] {
  const isLinked = new Set(linked);
  const linkedOrder = linkedInPriorityOrder(order, linked);
  return [
    first,
    ...linkedOrder.filter((platform) => platform !== first),
    ...order.filter((platform) => !isLinked.has(platform)),
  ];
}
