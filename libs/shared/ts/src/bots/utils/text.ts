/**
 * Text utilities for bot adapters: argument parsing, platform character
 * limits, single-message truncation, and multi-message chunking.
 *
 * These live in their own module (rather than the `index.ts` barrel) so that
 * sibling modules like `streaming.ts` can import them directly without creating
 * a barrel <-> module import cycle.
 */

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

/** Text-platform commands whose first token selects a subcommand. */
const SUBCOMMAND_COMMANDS = new Set(["todo", "workflow"]);

/**
 * Builds the args object for a text-platform command dispatch.
 *
 * For commands that take a subcommand it lifts the first
 * token of `rawText` into `args.subcommand`; every other command gets an empty
 * args object. Shared by the Slack, Telegram and WhatsApp adapters so the
 * subcommand rule lives in one place instead of an inline `if` in each.
 */
export function extractSubcommandArgs(
  commandName: string,
  rawText: string | undefined,
): Record<string, string | number | boolean | undefined> {
  if (!SUBCOMMAND_COMMANDS.has(commandName)) return {};
  return { subcommand: parseTextArgs(rawText ?? "").subcommand };
}

/**
 * Per-platform message character limits. Used by truncateResponse and
 * chunkResponse.
 *
 * Slack's hard API limit is ~40k, but messages render cleanly only well below
 * that — we cap at 3000 (not the 4000 block limit) for readable bubbles, the
 * same headroom the per-channel Slack sender used before delivery moved here.
 */
export const PLATFORM_LIMITS: Record<string, number> = {
  discord: 2000,
  slack: 3000,
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
 * Strips fenced code blocks (``` ... ```) so the parity checks only see
 * narrative text. Code can legitimately contain ``**`` (Python ``**kwargs``),
 * lone ``*`` (shell globs ``*.txt``), or stray backticks, and those bytes
 * must not poison emphasis parity for prose.
 */
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

/**
 * Counts single ``*`` markers in ``text``, excluding any ``*`` that is part
 * of a ``**`` (markdown bold). Used to detect WhatsApp-native ``*bold*``
 * pairs that the model emits when the platform context tells it to use
 * single-asterisk bold. Markdown bullets at line start (``^* ``) are also
 * excluded — they are not paired emphasis markers.
 */
function countSingleAsterisks(text: string): number {
  // Drop ``**`` first so the bold pairs don't double-count toward single-`*`.
  const noDouble = text.replaceAll("**", "");
  // Drop bullet-list ``*`` followed by a space at line start.
  const noBullets = noDouble.replaceAll(/^\*\s/gm, "");
  return (noBullets.match(/\*/g) ?? []).length;
}

/**
 * Returns true if cutting ``text`` at index ``idx`` would land inside an
 * unclosed markdown emphasis span. We check the markers that actually bite us
 * in WhatsApp output: ``**bold**``, single-asterisk ``*bold*`` (the
 * WhatsApp-native bold the platform context steers the model toward), and
 * `` `inline code` ``. ``_`` and ``~`` are skipped because they appear in
 * identifiers/URLs and the false-positive rate would shrink chunks
 * pointlessly.
 *
 * The check is symmetric: an odd number of a marker in the prefix AND a
 * closing marker somewhere in the suffix means the cut would orphan one
 * half of the pair.
 */
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

/**
 * Aggregate predicate — true when the cut at ``idx`` would split any markdown
 * span (link or emphasis). Keeps {@link pickCutBoundary} short.
 */
function cutsInsideMarkdown(text: string, idx: number): boolean {
  return cutsInsideMarkdownLink(text, idx) || cutsInsideEmphasisSpan(text, idx);
}

/**
 * Find the orphan single ``*`` to strip. Skips ``**`` (double-asterisk bold,
 * already handled separately) and ``* `` at line start (markdown bullet,
 * not an emphasis marker).
 *
 * @param scan - ``"tail"`` walks from the end (last orphan in chunk),
 *               ``"head"`` walks from the start (first orphan in next chunk).
 * @returns Index of the orphan ``*`` or -1 if none found.
 */
function findOrphanSingleAsterisk(text: string, scan: "tail" | "head"): number {
  const isBulletStart = (i: number): boolean => {
    const lineStart = text.lastIndexOf("\n", i - 1) + 1;
    // Ignore leading whitespace before checking ``*``
    let j = lineStart;
    while (j < i && (text[j] === " " || text[j] === "\t")) j++;
    return j === i && text[i + 1] === " ";
  };

  const indices: number[] = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "*") continue;
    if (text[i + 1] === "*") {
      i++; // skip second `*` of `**`
      continue;
    }
    if (text[i - 1] === "*") continue; // tail half of `**` (defensive)
    if (isBulletStart(i)) continue;
    indices.push(i);
  }
  if (indices.length === 0) return -1;
  return scan === "tail" ? (indices.at(-1) ?? -1) : indices[0];
}

/**
 * A pipe-delimited GFM table row — trimmed, starting and ending with ``|``
 * (e.g. ``| a | b |``). Exported so {@link formatters} can share one definition
 * instead of re-deriving the same check.
 */
export function isTableRow(line: string): boolean {
  const t = line.trim();
  return t.length >= 2 && t.startsWith("|") && t.endsWith("|");
}

/**
 * A GFM table separator row — a table row made up only of ``|``, ``-``, ``:``
 * and spaces (e.g. ``|---|:--:|``).
 */
export function isTableSeparator(line: string): boolean {
  const t = line.trim();
  return (
    isTableRow(t) &&
    t.includes("-") &&
    [...t].every((c) => c === "|" || c === "-" || c === ":" || c === " ")
  );
}

/**
 * Char-offset ranges ``[start, end)`` of every GFM table block in ``text`` (a
 * header row, a ``|---|`` separator, then contiguous body rows). Used by
 * {@link pickCutBoundary} to reject a cut that lands inside a table — the
 * per-chunk renderer needs the whole block contiguous, so a split table is
 * emitted to the user as raw ``| a | b |`` pipe rows.
 *
 * Only table blocks whose header starts at or before ``maxHeaderStart`` are
 * returned — pickCutBoundary never cuts past that offset, so tables beyond it
 * are irrelevant. A block that starts within the window but extends past it is
 * still scanned to its true end (so a straddling table is fully fenced off).
 * Bounding the scan keeps each call O(window) instead of O(whole remaining),
 * which matters because chunkResponse calls this once per chunk (and per
 * render-aware retry) over a shrinking tail.
 */
function findTableRanges(
  text: string,
  maxHeaderStart: number = text.length,
): [number, number][] {
  const len = text.length;
  const lineEnd = (start: number): number => {
    const nl = text.indexOf("\n", start);
    return nl === -1 ? len : nl;
  };

  const ranges: [number, number][] = [];
  let lineStart = 0;
  while (lineStart <= len && lineStart <= maxHeaderStart) {
    const headerEnd = lineEnd(lineStart);
    const sepStart = headerEnd + 1;
    const sepEnd = lineEnd(sepStart);
    if (
      isTableRow(text.slice(lineStart, headerEnd)) &&
      isTableSeparator(text.slice(sepStart, sepEnd))
    ) {
      let last = sepEnd;
      let rowStart = sepEnd + 1;
      while (rowStart <= len) {
        const rowEnd = lineEnd(rowStart);
        if (!isTableRow(text.slice(rowStart, rowEnd))) break;
        last = rowEnd;
        rowStart = rowEnd + 1;
      }
      ranges.push([lineStart, last]);
      lineStart = last + 1;
    } else {
      lineStart = headerEnd + 1;
    }
  }
  return ranges;
}

/**
 * Picks the best cut index ≤ ``limit`` for a chunk of ``text``. Prefers
 * paragraph (`\n\n`), then sentence enders, then word boundary, then a hard
 * cut at ``limit`` as a last resort. Boundaries that would split a markdown
 * link or a GFM table block are skipped.
 *
 * The 50 %-of-limit floor avoids producing tiny fragments — if no decent
 * boundary exists in the second half of the window, we accept the hard cut
 * rather than emit a 200-char chunk on a 4000-char limit.
 */
function pickCutBoundary(text: string, limit: number): number {
  const window = text.slice(0, limit);
  const floor = limit * 0.5;
  // Cuts are always ≤ limit, so only tables whose header starts within the
  // window can contain one — bound the scan there.
  const tableRanges = findTableRanges(text, limit);
  const unsafe = (idx: number): boolean =>
    cutsInsideMarkdown(text, idx) ||
    tableRanges.some(([start, end]) => idx > start && idx < end);

  // 1. Paragraph break
  const paragraph = window.lastIndexOf("\n\n");
  if (paragraph >= floor && !unsafe(paragraph)) {
    return paragraph;
  }

  // 2. Sentence end (in priority order: ". ", "! ", "? ", "\n")
  let bestSentence = -1;
  for (const sep of [". ", "! ", "? ", "\n"]) {
    const idx = window.lastIndexOf(sep);
    if (idx < floor) continue;
    const cut = idx + sep.length;
    if (cut > bestSentence && !unsafe(cut)) {
      bestSentence = cut;
    }
  }
  if (bestSentence > 0) return bestSentence;

  // 3. Word boundary
  let space = window.lastIndexOf(" ");
  while (space >= floor) {
    if (!unsafe(space + 1)) return space + 1;
    space = window.lastIndexOf(" ", space - 1);
  }

  // 4. Hard cut as last resort
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
 * Builds the (balanced) `[chunk, next]` pair for a raw cut of ``remaining`` at
 * ``rawLimit``. Picks the boundary, then balances emphasis markers and code
 * fences across the cut so each bubble renders as valid markdown.
 */
function splitAtBoundary(
  remaining: string,
  rawLimit: number,
): [string, string] {
  const cutAt = pickCutBoundary(remaining, rawLimit);
  let chunk = remaining.slice(0, cutAt);
  let next = remaining.slice(cutAt);

  const chunkNarrative = stripFencedBlocks(chunk);
  [chunk, next] = balanceDoubleAsterisks(chunk, next, chunkNarrative);
  [chunk, next] = balanceSingleAsterisks(chunk, next, chunkNarrative);

  // Balance code fences across the cut: if the chunk has an odd number of
  // ``` it ends inside an open fence — close it here and reopen on the next
  // chunk so each bubble renders as valid markdown.
  const fenceCount = chunk.match(/```/g)?.length ?? 0;
  if (fenceCount % 2 === 1) {
    chunk = `${chunk}\n\`\`\``;
    next = `\`\`\`\n${next}`;
  } else {
    // Cosmetic whitespace trim for narrative cuts only. We never trim when
    // the cut lands inside a fenced block, because leading whitespace there
    // is significant code indentation (Python, YAML) and trimming it would
    // produce broken code in the next bubble.
    chunk = chunk.trimEnd();
    next = next.trimStart();
  }
  return [chunk, next];
}

/** Smallest raw cut we will shrink to when a rendered chunk overflows. */
const MIN_RENDER_RAW_LIMIT = 256;
/** Cap on shrink retries per chunk (proportional shrink converges in ~1-2). */
const MAX_RENDER_SHRINK_ITERS = 6;

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
 * The platform limit applies to the message the platform actually receives. If
 * ``render`` is supplied, the chunk is measured by its RENDERED length and the
 * raw cut is shrunk until the rendered output fits — without a renderer, e.g.
 * Telegram's markdown→HTML table padding can inflate a 4096-char raw chunk past
 * the 4096-char API limit and the send is rejected.
 *
 * @param text - The full message text.
 * @param platform - The target platform (discord, slack, telegram, whatsapp).
 * @param render - Optional platform renderer; when given, chunk sizes are
 *   measured against the rendered output rather than the raw markdown.
 * @returns An array of chunks (raw markdown, in order); each is ≤ the platform
 *   limit after rendering. Returns ``[text]`` when ``text`` already fits.
 */
export function chunkResponse(
  text: string,
  platform: "discord" | "slack" | "telegram" | "whatsapp",
  render?: (chunk: string) => string,
): string[] {
  const limit = PLATFORM_LIMITS[platform];
  const measure = (s: string): number => (render ? render(s).length : s.length);
  if (measure(text) <= limit) return [text];

  // Reserve space for code-fence balancing markers ("\n```" + "```\n") so a
  // chunk that closes/reopens a fence still fits inside the platform limit.
  const FENCE_HEADROOM = 8;
  const cutLimit = limit - FENCE_HEADROOM;

  const chunks: string[] = [];
  let remaining = text;

  // `remaining.length > 0` guards termination: each iteration consumes a
  // non-empty prefix so `remaining` strictly shrinks. Looping on `measure()`
  // alone would spin forever for a renderer whose fixed overhead keeps even an
  // empty string over the limit.
  while (remaining.length > 0 && measure(remaining) > limit) {
    let rawLimit = cutLimit;
    let [chunk, next] = splitAtBoundary(remaining, rawLimit);

    // Render-aware: if the rendered chunk overflows, shrink the raw cut
    // proportionally to the overflow and re-split until it fits (or we hit the
    // floor — a single oversized atom like one giant table row that can't be
    // split further is sent best-effort).
    for (
      let i = 0;
      render &&
      rawLimit > MIN_RENDER_RAW_LIMIT &&
      measure(chunk) > limit &&
      i < MAX_RENDER_SHRINK_ITERS;
      i += 1
    ) {
      const renderedLen = measure(chunk) || 1;
      const scaled = Math.floor((rawLimit * limit) / renderedLen);
      rawLimit = Math.max(MIN_RENDER_RAW_LIMIT, Math.min(rawLimit - 1, scaled));
      [chunk, next] = splitAtBoundary(remaining, rawLimit);
    }

    chunks.push(chunk);
    remaining = next;
  }

  if (remaining.length > 0) chunks.push(remaining);
  return chunks.filter((c) => c.length > 0);
}
