/**
 * Shared helpers for `@<toolName>` mentions inside integration custom
 * instructions. The regex is the single source of truth for what counts as a
 * mention — segment building (chips) and autocomplete both derive from it.
 */

export const escapeRegExp = (value: string): string =>
  value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

/**
 * Regex matching `@<toolName>` for any of the given names. Longest names
 * first so e.g. "@Send Email" wins over "@Send". Boundaries on both sides so a
 * mention is only recognized as a standalone token: the leading `(?<!\w)` keeps
 * `foo@Send` / `name@Send.com` from matching, the trailing `(?!\w)` keeps a
 * prefix from matching inside a longer token ("@Send" vs "@Sender").
 */
const buildMentionRegex = (toolNames: string[]): RegExp | null => {
  if (toolNames.length === 0) return null;
  const alternation = toolNames
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  return new RegExp(String.raw`(?<!\w)@(?:${alternation})(?!\w)`, "g");
};

export const MENTION_LINK_PROTOCOL = "mention";
const MENTION_HREF_PREFIX = `${MENTION_LINK_PROTOCOL}:`;

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

/**
 * Decode a `mention:` link href back to the tool name, or null if the href
 * isn't a mention or carries malformed percent-encoding. Because the preview
 * renders arbitrary user markdown, a hand-typed `mention:%xx` must degrade to a
 * normal link rather than throw out of `decodeURIComponent`.
 */
export const decodeMentionHref = (href: string): string | null => {
  if (!href.startsWith(MENTION_HREF_PREFIX)) return null;
  try {
    return decodeURIComponent(href.slice(MENTION_HREF_PREFIX.length));
  } catch {
    return null;
  }
};

export interface MentionSegment {
  text: string;
  mention: boolean;
  offset: number;
}

/** The tool names mentioned as `@<name>` in the value, de-duplicated, in order. */
export const extractMentions = (
  value: string,
  toolNames: string[],
): string[] => {
  const seen = new Set<string>();
  for (const segment of buildMentionSegments(value, toolNames)) {
    if (segment.mention) seen.add(segment.text.slice(1));
  }
  return [...seen];
};

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
