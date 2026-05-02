/**
 * Bot utility barrel export.
 *
 * Three layers of reusable logic, ordered from low-level to high-level:
 *
 * 1. formatters - Pure functions that turn data into display strings.
 *    Use these when you need custom response assembly.
 *
 * 2. commands  - Business-logic handlers that call GaiaClient, format results,
 *    and return a ready-to-send string. Bot adapters call these directly.
 *
 * 3. streaming - handleStreamingChat: full streaming lifecycle handler.
 *    Bot adapters provide three callbacks (editMessage, onAuthError, onGenericError)
 *    and the shared function handles throttling, cursor display, and error routing.
 *
 * Platform character limits and truncation are also exported here.
 */

export * from "./commands";
export * from "./formatters";
export * from "./logger";
export * from "./streaming";

/**
 * Parses whitespace-separated text into a subcommand and remaining args.
 * Used by Slack and Telegram command handlers where input is plain text.
 *
 * @param text - Raw command text.
 * @param skipFirst - If true, skips the first token (e.g. for Telegram where the command name is included).
 * @returns The parsed subcommand (defaults to "list") and remaining args.
 */
export function parseTextArgs(
  text: string,
  skipFirst = false,
): { subcommand: string; args: string[] } {
  const parts = text.trim().split(/\s+/);
  const tokens = skipFirst ? parts.slice(1) : parts;
  return { subcommand: tokens[0] || "list", args: tokens.slice(1) };
}

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
 *
 * @param text - The message text to truncate.
 * @param platform - The target platform (discord, slack, telegram, whatsapp).
 * @param conversationUrl - Optional URL to the full conversation on the web app.
 * @returns The truncated message.
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

  // Truncate at word boundary, avoiding cuts inside markdown links
  let truncated = text.slice(0, maxLen);
  const lastSpace = truncated.lastIndexOf(" ");
  if (lastSpace > maxLen * 0.8) {
    truncated = truncated.slice(0, lastSpace);
  }

  // If we cut inside a markdown link [label](url), backtrack to before the link
  const lastOpenBracket = truncated.lastIndexOf("[");
  if (lastOpenBracket > -1) {
    const closeParen = text.indexOf(")", lastOpenBracket);
    if (closeParen > -1 && closeParen > truncated.length) {
      // We're inside an incomplete link — backtrack to before it
      const beforeLink = truncated.lastIndexOf("\n", lastOpenBracket);
      if (beforeLink > maxLen * 0.5) {
        truncated = truncated.slice(0, beforeLink);
      }
    }
  }

  return truncated + suffix;
}

/**
 * Returns true if cutting ``text`` at index ``idx`` would land inside an
 * incomplete markdown link of the form ``[label](url)``. Used by
 * {@link chunkResponse} to walk the cut boundary back to before the link so
 * we never deliver a half-rendered link to the user.
 */
function cutsInsideMarkdownLink(text: string, idx: number): boolean {
  const lastOpenBracket = text.lastIndexOf("[", idx - 1);
  if (lastOpenBracket === -1) return false;
  // If a `]` appears between `[` and idx the bracket is already closed.
  if (text.lastIndexOf("]", idx - 1) > lastOpenBracket) {
    // Bracket closed — but if `(` follows immediately, the URL portion may
    // still be open at idx. Check for an unclosed `(` to the left of idx.
    const lastOpenParen = text.lastIndexOf("(", idx - 1);
    const lastCloseParen = text.lastIndexOf(")", idx - 1);
    if (lastOpenParen > lastCloseParen) {
      const closeAfter = text.indexOf(")", idx);
      return closeAfter !== -1;
    }
    return false;
  }
  // Bracket is still open at idx — definitely inside a link.
  const closeParen = text.indexOf(")", lastOpenBracket);
  return closeParen !== -1;
}

/**
 * Returns true if cutting ``text`` at index ``idx`` would land inside an
 * unclosed markdown emphasis span. We only check the two markers that bite us
 * in practice: ``**bold**`` (model emits markdown bold even when output goes
 * to WhatsApp) and `` `inline code` ``. Single ``*``, ``_``, ``~`` are skipped
 * because they appear in code identifiers, URLs, and plain prose — the false
 * positive rate is too high to be worth the rare valid catch.
 *
 * The check is symmetric: an odd number of ``**`` in the prefix AND a closing
 * ``**`` somewhere in the suffix means the cut would orphan one half of the
 * pair. Same logic for backticks (excluding triple-backticks, which are
 * handled separately by the fence-balancing step in {@link chunkResponse}).
 */
function cutsInsideEmphasisSpan(text: string, idx: number): boolean {
  const prefix = text.slice(0, idx);
  const suffix = text.slice(idx);

  // Strip fenced code blocks (``` ... ```) before counting markers — code can
  // legitimately contain ``**`` (e.g. Python ``**kwargs``) and stray
  // backticks (e.g. shell quoting), and those bytes must not poison the
  // emphasis parity check that's deciding cut positions in narrative text.
  const stripFences = (s: string): string => {
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
  };
  const prefixNarrative = stripFences(prefix);
  const suffixNarrative = stripFences(suffix);

  const doubleAsteriskOpens = (prefixNarrative.match(/\*\*/g) ?? []).length;
  if (doubleAsteriskOpens % 2 === 1 && suffixNarrative.includes("**"))
    return true;

  const inlineTickOpens = (prefixNarrative.match(/`/g) ?? []).length;
  if (inlineTickOpens % 2 === 1 && suffixNarrative.includes("`")) return true;

  return false;
}

/**
 * Aggregate predicate — true when the cut at ``idx`` would split any markdown
 * span (link or emphasis). Keeps {@link pickCutBoundary} short.
 */
function cutsInsideMarkdown(text: string, idx: number): boolean {
  return cutsInsideMarkdownLink(text, idx) || cutsInsideEmphasisSpan(text, idx);
}

/**
 * Picks the best cut index ≤ ``limit`` for a chunk of ``text``. Prefers
 * paragraph (`\n\n`), then sentence enders, then word boundary, then a hard
 * cut at ``limit`` as a last resort. Boundaries that would split a markdown
 * link are skipped.
 *
 * The 50 %-of-limit floor avoids producing tiny fragments — if no decent
 * boundary exists in the second half of the window, we accept the hard cut
 * rather than emit a 200-char chunk on a 4000-char limit.
 */
function pickCutBoundary(text: string, limit: number): number {
  const window = text.slice(0, limit);
  const floor = limit * 0.5;

  // 1. Paragraph break
  const paragraph = window.lastIndexOf("\n\n");
  if (paragraph >= floor && !cutsInsideMarkdown(text, paragraph)) {
    return paragraph;
  }

  // 2. Sentence end (in priority order: ". ", "! ", "? ", "\n")
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

  // 3. Word boundary
  let space = window.lastIndexOf(" ");
  while (space >= floor) {
    if (!cutsInsideMarkdown(text, space + 1)) return space + 1;
    space = window.lastIndexOf(" ", space - 1);
  }

  // 4. Hard cut as last resort
  return limit;
}

/**
 * Splits a long response into platform-sized chunks for delivery as multiple
 * messages instead of a single truncated bubble. Used by bot adapters so the
 * user receives the full content across as many bubbles as needed.
 *
 * The boundary search prefers paragraph breaks, then sentence enders, then
 * word boundaries, then a hard cut. Boundaries that would land inside a
 * markdown link `[text](url)` are skipped. If a chunk would end with an
 * unclosed code fence (```), the chunk is closed and the next chunk reopens
 * with the same fence so the markdown stays valid across bubbles.
 *
 * Each returned chunk is guaranteed to be ≤ the platform character limit
 * (after fence-balancing, the closing/reopening adds a small fixed overhead;
 * we leave headroom by reserving 8 chars for the fence pair).
 *
 * @param text - The full message text.
 * @param platform - The target platform (discord, slack, telegram, whatsapp).
 * @returns An array of chunks, in order, each ≤ the platform character limit.
 *   Returns ``[text]`` when ``text`` already fits.
 */
export function chunkResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
): string[] {
  const limit = PLATFORM_LIMITS[platform];
  if (text.length <= limit) return [text];

  // Reserve space for code-fence balancing markers ("\n```" + "```\n") so a
  // chunk that closes/reopens a fence still fits inside the platform limit.
  const FENCE_HEADROOM = 8;
  const cutLimit = limit - FENCE_HEADROOM;

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > limit) {
    const cutAt = pickCutBoundary(remaining, cutLimit);
    let chunk = remaining.slice(0, cutAt).trimEnd();
    let next = remaining.slice(cutAt).trimStart();

    // Belt-and-suspenders: balance unbalanced ``**`` markers across the cut
    // in narrative text. We ignore ``**`` that appears inside fenced code
    // blocks (Python ``**kwargs`` etc.) so legitimate code doesn't flip the
    // parity and mask a real orphan in prose.
    const stripFences = (s: string): string => {
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
    };
    const chunkOpens = (stripFences(chunk).match(/\*\*/g) ?? []).length;
    if (chunkOpens % 2 === 1) {
      // Strip the orphan ``**`` from the chunk's narrative tail and the
      // matching opener from the next chunk's narrative head so
      // convertToWhatsAppMarkdown's pair regex does not greedily merge them
      // with unrelated ``**`` pairs and emit stray asterisks.
      const lastIdx = chunk.lastIndexOf("**");
      if (lastIdx !== -1) {
        chunk = chunk.slice(0, lastIdx) + chunk.slice(lastIdx + 2);
      }
      const firstIdx = next.indexOf("**");
      if (firstIdx !== -1) {
        next = next.slice(0, firstIdx) + next.slice(firstIdx + 2);
      }
    }

    // Balance code fences across the cut: if the chunk has an odd number of
    // ``` it ends inside an open fence — close it here and reopen on the next
    // chunk so each bubble renders as valid markdown.
    const fenceCount = chunk.match(/```/g)?.length ?? 0;
    if (fenceCount % 2 === 1) {
      chunk = `${chunk}\n\`\`\``;
      next = `\`\`\`\n${next}`;
    }

    chunks.push(chunk);
    remaining = next;
  }

  if (remaining.length > 0) chunks.push(remaining);
  return chunks.filter((c) => c.length > 0);
}
