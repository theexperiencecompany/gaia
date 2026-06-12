/**
 * Shared helpers for `@<toolName>` mentions inside integration custom
 * instructions. The regex is the single source of truth for what counts as a
 * mention — segment building (chips) and autocomplete both derive from it.
 */

export const escapeRegExp = (value: string): string =>
  value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

/**
 * Regex matching `@<toolName>` for any of the given names. Longest names
 * first so e.g. "@Send Email" wins over "@Send"; trailing boundary so a
 * prefix doesn't match inside a longer token ("@Send" vs "@Sender").
 */
const buildMentionRegex = (toolNames: string[]): RegExp | null => {
  if (toolNames.length === 0) return null;
  const alternation = toolNames
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  return new RegExp(String.raw`@(?:${alternation})(?!\w)`, "g");
};

export const MENTION_LINK_PROTOCOL = "mention";
export const MENTION_HREF_PREFIX = `${MENTION_LINK_PROTOCOL}:`;

/**
 * Rewrite `@<toolName>` mentions as `[@<toolName>](mention:<toolName>)`
 * markdown links so a renderer can swap them for chips.
 */
export const mentionsToMarkdownLinks = (
  value: string,
  toolNames: string[],
): string => {
  const re = buildMentionRegex(toolNames);
  if (!re) return value;
  return value.replace(
    re,
    (match) =>
      `[${match}](${MENTION_HREF_PREFIX}${encodeURIComponent(match.slice(1))})`,
  );
};

export interface MentionSegment {
  text: string;
  mention: boolean;
  offset: number;
}

/** Split text on `@<toolName>` occurrences so mentions can render as chips. */
export const buildMentionSegments = (
  value: string,
  toolNames: string[],
): MentionSegment[] => {
  const re = buildMentionRegex(toolNames);
  if (!re) return [{ text: value, mention: false, offset: 0 }];
  const segments: MentionSegment[] = [];
  let last = 0;
  for (const match of value.matchAll(re)) {
    const index = match.index ?? 0;
    if (index > last)
      segments.push({
        text: value.slice(last, index),
        mention: false,
        offset: last,
      });
    segments.push({ text: match[0], mention: true, offset: index });
    last = index + match[0].length;
  }
  if (last < value.length)
    segments.push({ text: value.slice(last), mention: false, offset: last });
  return segments;
};
