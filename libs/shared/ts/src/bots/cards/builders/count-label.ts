/** "1 event", "3 events": a count with its noun agreeing, for a card's title. */
export function countLabel(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
