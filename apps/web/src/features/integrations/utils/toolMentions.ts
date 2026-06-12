/**
 * Shared helpers for `@<toolName>` mentions inside integration custom
 * instructions. The regex is the single source of truth for what counts as a
 * mention — the editor backdrop, the chip strip, and removal all use it.
 */

export const escapeRegExp = (value: string): string =>
  value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

/**
 * Regex matching `@<toolName>` for any of the given names. Longest names
 * first so e.g. "@Send Email" wins over "@Send"; trailing boundary so a
 * prefix doesn't match inside a longer token ("@Send" vs "@Sender").
 */
export const buildMentionRegex = (toolNames: string[]): RegExp | null => {
  if (toolNames.length === 0) return null;
  const alternation = toolNames
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  return new RegExp(String.raw`@(?:${alternation})(?!\w)`, "g");
};

/** Unique mentioned tool names (without the `@`), in order of appearance. */
export const extractMentionedTools = (
  value: string,
  toolNames: string[],
): string[] => {
  const re = buildMentionRegex(toolNames);
  if (!re) return [];
  const seen = new Set<string>();
  for (const match of value.matchAll(re)) seen.add(match[0].slice(1));
  return Array.from(seen);
};

/** Remove every `@<toolName>` occurrence (plus one trailing space, if any). */
export const removeToolMention = (value: string, toolName: string): string => {
  const re = new RegExp(String.raw`@${escapeRegExp(toolName)}(?!\w) ?`, "g");
  return value.replace(re, "");
};
