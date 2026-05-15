/**
 * Response sizing utilities for bot platforms — truncation and chunking
 * that respect platform character limits and never split markdown spans.
 *
 * Extracted from utils/index.ts to break the index → streaming → index
 * circular dependency that the original layout introduced.
 */

/** Per-platform message character limits. Used by truncateResponse. */
export const PLATFORM_LIMITS: Record<string, number> = {
  discord: 2000,
  slack: 4000,
  telegram: 4096,
  whatsapp: 4096,
};

/**
 * Truncates a response message to fit within the platform's character limit.
 * Truncates at word boundaries and optionally appends a web app link.
 */
export function truncateResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
  conversationUrl?: string,
): string {
  const limit = PLATFORM_LIMITS[platform];
  if (text.length <= limit) {
    return text;
  }

  const suffix = conversationUrl
    ? `\n\n[View full response](${conversationUrl})`
    : "\n\n... (truncated)";
  const maxLen = limit - suffix.length;

  let truncated = text.slice(0, maxLen);
  const lastSpace = truncated.lastIndexOf(" ");
  if (lastSpace > maxLen * 0.8) {
    truncated = truncated.slice(0, lastSpace);
  }

  const lastOpenBracket = truncated.lastIndexOf("[");
  if (lastOpenBracket > -1) {
    const closeParen = text.indexOf(")", lastOpenBracket);
    if (closeParen > -1 && closeParen > truncated.length) {
      const beforeLink = truncated.lastIndexOf("\n", lastOpenBracket);
      if (beforeLink > maxLen * 0.5) {
        truncated = truncated.slice(0, beforeLink);
      }
    }
  }

  return truncated + suffix;
}

function cutsInsideMarkdownLink(text: string, idx: number): boolean {
  const lastOpenBracket = text.lastIndexOf("[", idx - 1);
  if (lastOpenBracket === -1) return false;
  if (text.lastIndexOf("]", idx - 1) > lastOpenBracket) {
    const lastOpenParen = text.lastIndexOf("(", idx - 1);
    const lastCloseParen = text.lastIndexOf(")", idx - 1);
    if (lastOpenParen > lastCloseParen) {
      const closeAfter = text.indexOf(")", idx);
      return closeAfter !== -1;
    }
    return false;
  }
  const closeParen = text.indexOf(")", lastOpenBracket);
  return closeParen !== -1;
}

function stripFencedBlocks(s: string): string {
  let out = "";
  let inFence = false;
  let i = 0;
  while (i < s.length) {
    if (s.startsWith("```", i)) {
      inFence = !inFence;
      i += 3;
      continue;
    }
    if (!inFence) out += s[i];
    i++;
  }
  return out;
}

function countSingleAsterisks(text: string): number {
  const noDouble = text.replaceAll("**", "");
  const noBullets = noDouble.replaceAll(/^\*\s/gm, "");
  return (noBullets.match(/\*/g) ?? []).length;
}

function cutsInsideEmphasisSpan(text: string, idx: number): boolean {
  const prefixNarrative = stripFencedBlocks(text.slice(0, idx));
  const suffixNarrative = stripFencedBlocks(text.slice(idx));

  const doubleAsteriskOpens = (prefixNarrative.match(/\*\*/g) ?? []).length;
  if (doubleAsteriskOpens % 2 === 1 && suffixNarrative.includes("**"))
    return true;

  const singleAsteriskOpens = countSingleAsterisks(prefixNarrative);
  if (
    singleAsteriskOpens % 2 === 1 &&
    countSingleAsterisks(suffixNarrative) > 0
  )
    return true;

  const inlineTickOpens = (prefixNarrative.match(/`/g) ?? []).length;
  if (inlineTickOpens % 2 === 1 && suffixNarrative.includes("`")) return true;

  return false;
}

function cutsInsideMarkdown(text: string, idx: number): boolean {
  return cutsInsideMarkdownLink(text, idx) || cutsInsideEmphasisSpan(text, idx);
}

function findOrphanSingleAsterisk(text: string, scan: "tail" | "head"): number {
  const isBulletStart = (i: number): boolean => {
    const lineStart = text.lastIndexOf("\n", i - 1) + 1;
    let j = lineStart;
    while (j < i && (text[j] === " " || text[j] === "\t")) j++;
    return j === i && text[i + 1] === " ";
  };

  const indices: number[] = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "*") continue;
    if (text[i + 1] === "*") {
      i++;
      continue;
    }
    if (text[i - 1] === "*") continue;
    if (isBulletStart(i)) continue;
    indices.push(i);
  }
  if (indices.length === 0) return -1;
  return scan === "tail" ? (indices.at(-1) ?? -1) : indices[0];
}

function pickCutBoundary(text: string, limit: number): number {
  const window = text.slice(0, limit);
  const floor = limit * 0.5;

  const paragraph = window.lastIndexOf("\n\n");
  if (paragraph >= floor && !cutsInsideMarkdown(text, paragraph)) {
    return paragraph;
  }

  let bestSentence = -1;
  for (const sep of [". ", "! ", "? ", "\n"]) {
    const idx = window.lastIndexOf(sep);
    if (idx < floor) continue;
    const cut = idx + sep.length;
    if (cut > bestSentence && !cutsInsideMarkdown(text, cut)) {
      bestSentence = cut;
    }
  }
  if (bestSentence > 0) return bestSentence;

  let space = window.lastIndexOf(" ");
  while (space >= floor) {
    if (!cutsInsideMarkdown(text, space + 1)) return space + 1;
    space = window.lastIndexOf(" ", space - 1);
  }

  return limit;
}

function balanceDoubleAsterisks(
  chunk: string,
  next: string,
  chunkNarrative: string,
): [string, string] {
  const doubleOpens = (chunkNarrative.match(/\*\*/g) ?? []).length;
  if (doubleOpens % 2 !== 1) return [chunk, next];
  const lastIdx = chunk.lastIndexOf("**");
  if (lastIdx !== -1) {
    chunk = chunk.slice(0, lastIdx) + chunk.slice(lastIdx + 2);
  }
  const firstIdx = next.indexOf("**");
  if (firstIdx !== -1) {
    next = next.slice(0, firstIdx) + next.slice(firstIdx + 2);
  }
  return [chunk, next];
}

function balanceSingleAsterisks(
  chunk: string,
  next: string,
  chunkNarrative: string,
): [string, string] {
  if (countSingleAsterisks(chunkNarrative) % 2 !== 1) return [chunk, next];
  const lastIdx = findOrphanSingleAsterisk(chunk, "tail");
  if (lastIdx !== -1) {
    chunk = chunk.slice(0, lastIdx) + chunk.slice(lastIdx + 1);
  }
  const firstIdx = findOrphanSingleAsterisk(next, "head");
  if (firstIdx !== -1) {
    next = next.slice(0, firstIdx) + next.slice(firstIdx + 1);
  }
  return [chunk, next];
}

/**
 * Splits a long response into platform-sized chunks for delivery as multiple
 * messages instead of a single truncated bubble.
 */
export function chunkResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
): string[] {
  const limit = PLATFORM_LIMITS[platform];
  if (text.length <= limit) return [text];

  const FENCE_HEADROOM = 8;
  const cutLimit = limit - FENCE_HEADROOM;

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > limit) {
    const cutAt = pickCutBoundary(remaining, cutLimit);
    let chunk = remaining.slice(0, cutAt);
    let next = remaining.slice(cutAt);

    const chunkNarrative = stripFencedBlocks(chunk);
    [chunk, next] = balanceDoubleAsterisks(chunk, next, chunkNarrative);
    [chunk, next] = balanceSingleAsterisks(chunk, next, chunkNarrative);

    const fenceCount = chunk.match(/```/g)?.length ?? 0;
    const insideFence = fenceCount % 2 === 1;
    if (insideFence) {
      chunk = `${chunk}\n\`\`\``;
      next = `\`\`\`\n${next}`;
    } else {
      chunk = chunk.trimEnd();
      next = next.trimStart();
    }

    chunks.push(chunk);
    remaining = next;
  }

  if (remaining.length > 0) chunks.push(remaining);
  return chunks.filter((c) => c.length > 0);
}
