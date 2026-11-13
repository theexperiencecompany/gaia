/**
 * Pieces the read-only result cards (search, Reddit, X, weather) share: which
 * URLs a card may link to, the muted meta line, snippets and counts, and a capped list.
 *
 * @module
 */
import { formatCompactNumber, truncateText } from "../../../utils/formatters";
import type { CardListBlock, CardListItem } from "../types";

const HTTPS_PROTOCOL = "https:";
const META_SEPARATOR = " · ";

/** `value` when it is an absolute https URL: the only kind a card links to or embeds. */
export function httpsUrl(value: string | null | undefined): string | undefined {
  if (!value || !URL.canParse(value)) return undefined;
  return new URL(value).protocol === HTTPS_PROTOCOL ? value : undefined;
}

/** The site a URL is on, e.g. "example.com", for a result's meta line. */
export function urlHost(url: string): string {
  return new URL(url).hostname;
}

/** A muted meta line from whichever parts are present; `undefined` when none are. */
export function joinMeta(
  parts: ReadonlyArray<string | null | undefined>,
): string | undefined {
  const present = parts.filter((part): part is string => Boolean(part));
  return present.length > 0 ? present.join(META_SEPARATOR) : undefined;
}

/** "Clear sky" from a source's lowercase "clear sky". */
export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The trimmed start of a long text, for a list row's snippet; `undefined` when blank. */
export function snippet(
  text: string | null | undefined,
  max: number,
): string | undefined {
  const trimmed = text?.trim();
  return trimmed ? truncateText(trimmed, max) : undefined;
}

/** "1.2k likes", "1 like" for a meta line; `null` when the source did not count it. */
export function countOf(
  value: number | undefined,
  singular: string,
  plural = `${singular}s`,
): string | null {
  if (value == null) return null;
  return `${formatCompactNumber(value)} ${value === 1 ? singular : plural}`;
}

/** The first `max` of `source` as list rows, and how many more there were. */
export function cappedList<T>(
  source: readonly T[],
  max: number,
  toItem: (entry: T) => CardListItem,
): CardListBlock {
  return {
    kind: "list",
    items: source.slice(0, max).map(toItem),
    hiddenCount: Math.max(0, source.length - max),
  };
}
