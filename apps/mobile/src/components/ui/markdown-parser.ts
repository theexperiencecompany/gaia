/**
 * Pure streaming-markdown parser — no React Native imports so it can be unit
 * tested directly. Consumed by markdown-renderer.tsx, which owns all styling
 * and rendering.
 */

// -- Types --------------------------------------------------------------------

type InlineSegment =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "italic"; text: string }
  | { type: "boldItalic"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; url: string }
  | { type: "image"; alt: string; url: string }
  | { type: "strikethrough"; text: string }
  | { type: "mathInline"; text: string };

interface ListItem {
  blocks: Block[];
  task: boolean;
  checked: boolean;
}

type TableAlignment = "left" | "center" | "right" | null;

type Block =
  | { type: "paragraph"; segments: InlineSegment[] }
  | { type: "heading"; level: number; segments: InlineSegment[] }
  | { type: "codeBlock"; language: string; code: string }
  | { type: "blockquote"; segments: InlineSegment[] }
  | { type: "list"; ordered: boolean; start: number; items: ListItem[] }
  | { type: "table"; alignments: TableAlignment[]; rows: string[][] }
  | { type: "hr" }
  | { type: "mathBlock"; code: string };

// -- Streaming repair ---------------------------------------------------------

/**
 * Patch the most common incomplete-markdown states while tokens are still
 * arriving, so partial output renders as text rather than raw markers
 * (mirrors Streamdown's parseIncompleteMarkdown on web):
 *  - unclosed ``` fence → close it so the half-streamed code renders as a block
 *  - unclosed $$ math fence → close it
 *  - dangling inline emphasis/code markers at end of text → close them
 */
export function repairStreamingMarkdown(md: string): string {
  let out = md;

  const fenceCount = (out.match(/^[^\S\n]*```/gm) ?? []).length;
  if (fenceCount % 2 === 1) out += "\n```";

  const mathFenceCount = (out.match(/^\$\$/gm) ?? []).length;
  if (mathFenceCount % 2 === 1) out += "\n$$";

  // Close dangling inline markers, longest first, recounting after each append
  // so an appended marker doesn't skew later parity checks.
  for (const marker of ["**", "__", "~~"]) {
    const count = (
      out.match(new RegExp(marker.replace(/\*/g, "\\*"), "g")) ?? []
    ).length;
    if (count % 2 === 1) out += marker;
  }
  const backtickCount = (out.match(/`/g) ?? []).length;
  if (backtickCount % 2 === 1) out += "`";
  // Single-marker emphasis (* and _): only append when the trailing run looks
  // like an unclosed opener — a lone marker at the very end of the text.
  for (const marker of ["*", "_"]) {
    if (out.endsWith(marker) && !out.endsWith(marker.repeat(2))) {
      // Count non-doubled occurrences conservatively; appending only when the
      // text ends with exactly one avoids corrupting valid mid-text emphasis.
      out += marker;
    }
  }

  return out;
}

// -- Entity decoding ----------------------------------------------------------

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  nbsp: " ",
  "#39": "'",
};

function decodeEntities(text: string): string {
  return text.replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, entity: string) => {
    return ENTITIES[entity] ?? `&${entity};`;
  });
}

// -- Inline parsing -----------------------------------------------------------

function segmentFromMatch(match: RegExpExecArray): InlineSegment | null {
  if (match[2] !== undefined) {
    return { type: "image", alt: match[1] ?? "", url: match[2] };
  }
  if (match[3] !== undefined && match[4] !== undefined) {
    return { type: "link", text: match[3], url: match[4] };
  }
  if (match[5] || match[6]) {
    return { type: "boldItalic", text: match[5] || match[6] };
  }
  if (match[7] || match[8]) {
    return { type: "bold", text: match[7] || match[8] };
  }
  if (match[9] || match[10]) {
    return { type: "italic", text: match[9] || match[10] };
  }
  if (match[11]) {
    return { type: "strikethrough", text: match[11] };
  }
  if (match[12]) {
    return { type: "mathInline", text: match[12] };
  }
  if (match[13]) {
    return { type: "code", text: match[13] };
  }
  return null;
}

// Order matters: image before link; bold-italic before bold before italic;
// $...$ before backtick.
const INLINE_REGEX = new RegExp(
  [
    /!\[([^\]]*)\]\(([^)]+)\)/.source, // 1-2 image
    /\[([^\]]+)\]\(([^)]+)\)/.source, // 3-4 link
    /\*\*\*([\s\S]+?)\*\*\*/.source, // 5 bold-italic ***
    /___([\s\S]+?)___/.source, // 6 bold-italic ___
    /\*\*([\s\S]+?)\*\*/.source, // 7 bold **
    /__([\s\S]+?)__/.source, // 8 bold __
    /(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])/.source, // 9 italic *
    /(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])/.source, // 10 italic _
    /~~([\s\S]+?)~~/.source, // 11 strikethrough
    /\$([^$\n]+?)\$/.source, // 12 math inline
    /`([^`\n]+)`/.source, // 13 code
  ].join("|"),
  "g",
);

function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  INLINE_REGEX.lastIndex = 0;
  let lastIndex = 0;
  let match = INLINE_REGEX.exec(text);

  while (match !== null) {
    if (match.index > lastIndex) {
      segments.push({
        type: "text",
        text: decodeEntities(text.slice(lastIndex, match.index)),
      });
    }

    const segment = segmentFromMatch(match);
    if (segment) {
      segments.push(segment);
    }

    lastIndex = match.index + match[0].length;
    match = INLINE_REGEX.exec(text);
  }

  if (lastIndex < text.length) {
    segments.push({
      type: "text",
      text: decodeEntities(text.slice(lastIndex)),
    });
  }

  if (segments.length === 0) {
    segments.push({ type: "text", text: decodeEntities(text) });
  }

  return segments;
}

// -- Block parsing ------------------------------------------------------------

// A single parsing step: an optional block plus the index to resume from.
// `block === null` means lines were consumed without producing a block.
type BlockParseResult = { block: Block | null; next: number };

function parseMathBlockLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  if (lines[start].trim() !== "$$") return null;
  const mathLines: string[] = [];
  let i = start + 1;
  while (i < lines.length && lines[i].trim() !== "$$") {
    mathLines.push(lines[i]);
    i++;
  }
  i++; // skip closing $$
  return { block: { type: "mathBlock", code: mathLines.join("\n") }, next: i };
}

function parseCodeBlockLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  if (!lines[start].trimStart().startsWith("```")) return null;
  const language = lines[start].trimStart().slice(3).trim();
  const codeLines: string[] = [];
  let i = start + 1;
  while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
    codeLines.push(lines[i]);
    i++;
  }
  i++; // skip closing ```
  return {
    block: { type: "codeBlock", language, code: codeLines.join("\n") },
    next: i,
  };
}

// Captures the first marker and requires every repeat to match it, so mixed
// sequences like "- * _" stay text (CommonMark only treats a uniform run as a
// rule). Unambiguous by construction (every \s* is anchored between mandatory
// chars), so it cannot backtrack exponentially on adversarial input.
const HR_LINE_REGEX = /^\s*([-*_])(?:\s*\1){2,}\s*$/;

function isHrLine(line: string): boolean {
  return HR_LINE_REGEX.test(line);
}

function parseHrLine(lines: string[], start: number): BlockParseResult | null {
  if (!isHrLine(lines[start])) return null;
  return { block: { type: "hr" }, next: start + 1 };
}

const HEADING_LINE_REGEX = /^(#{1,6})\s+(.+)/;

function parseHeadingLine(
  lines: string[],
  start: number,
): BlockParseResult | null {
  const headingMatch = lines[start].match(HEADING_LINE_REGEX);
  if (!headingMatch) return null;
  return {
    block: {
      type: "heading",
      level: headingMatch[1].length,
      segments: parseInline(headingMatch[2]),
    },
    next: start + 1,
  };
}

// `>` with or without a trailing space opens a quote (CommonMark allows both).
const BLOCKQUOTE_LINE_REGEX = /^\s{0,3}>\s?(.*)$/;

function parseBlockquoteLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  const openMatch = lines[start].match(BLOCKQUOTE_LINE_REGEX);
  if (!openMatch) return null;
  const quoteLines: string[] = [openMatch[1]];
  let i = start + 1;
  while (i < lines.length) {
    const match = lines[i].match(BLOCKQUOTE_LINE_REGEX);
    if (!match) break;
    quoteLines.push(match[1]);
    i++;
  }
  return {
    block: { type: "blockquote", segments: parseInline(quoteLines.join("\n")) },
    next: i,
  };
}

// -- Lists (nested + task lists) ----------------------------------------------

const UNORDERED_ITEM_REGEX = /^(\s*)([-*+])\s+(.*)$/;
const ORDERED_ITEM_REGEX = /^(\s*)(\d+)[.)]\s+(.*)$/;
const TASK_CHECKBOX_REGEX = /^\[([ xX])\]\s+(.*)$/;

/** Marker info for a list-item line, or null when the line opens no item. */
function itemMarker(
  line: string,
  ordered: boolean,
): { indent: number; rest: string } | null {
  const match = ordered
    ? line.match(ORDERED_ITEM_REGEX)
    : line.match(UNORDERED_ITEM_REGEX);
  if (!match) return null;
  return { indent: match[1].length, rest: match[3] };
}

/**
 * Parse a (possibly nested) list starting at `start`. Items at the opening
 * line's indent delimit items; deeper-indented continuation lines belong to
 * the current item and are recursively parsed as blocks, which is what makes
 * nested sublists render correctly.
 */
function parseListLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  const ordered = ORDERED_ITEM_REGEX.test(lines[start]);
  const first = itemMarker(lines[start], ordered);
  if (!first) return null;

  const baseIndent = first.indent;
  const items: ListItem[] = [];

  let i = start;
  while (i < lines.length) {
    const line = lines[i];
    const marker = itemMarker(line, ordered);

    // A sibling item at the same level opens a new entry.
    if (!marker || marker.indent < baseIndent) break;

    const task = marker.rest.match(TASK_CHECKBOX_REGEX);
    const itemLines = [task ? task[2] : marker.rest];
    items.push({
      blocks: [],
      task: !!task,
      checked: task ? task[1].toLowerCase() === "x" : false,
    });
    i++;

    // Continuation lines belong to this item: nested sublists (deeper-indent
    // markers) and indented wrapped text. Anything else ends the item; the
    // recursive parseBlocks on itemLines is what renders nested lists.
    while (i < lines.length && lines[i].trim() !== "") {
      const cont = lines[i];
      const contIndent = cont.match(/^\s*/)?.[0].length ?? 0;
      const nestedMarker = itemMarker(cont, ordered);
      const isNested =
        (nestedMarker && nestedMarker.indent > baseIndent) ||
        contIndent > baseIndent + 1;
      if (!isNested) break;
      itemLines.push(cont.trimStart());
      i++;
    }
    items[items.length - 1].blocks = parseBlocks(itemLines);
  }

  const startIndex = ordered
    ? Number.parseInt(lines[start].match(ORDERED_ITEM_REGEX)?.[2] ?? "1", 10)
    : 1;

  return {
    block: {
      type: "list",
      ordered,
      start: Number.isNaN(startIndex) ? 1 : startIndex,
      items,
    },
    next: i,
  };
}

// -- Tables -------------------------------------------------------------------

const TABLE_DELIM_REGEX = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/;

// Protect escaped pipes, split, then restore. A sentinel string rather than
// a control character so the split stays regex-free.
const ESCAPED_PIPE_SENTINEL = "\u0001gaia-pipe\u0001";
function splitTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|") && !trimmed.endsWith("\\|")) {
    trimmed = trimmed.slice(0, -1);
  }
  return trimmed
    .replace(/\\\|/g, ESCAPED_PIPE_SENTINEL)
    .split("|")
    .map((cell) => cell.replaceAll(ESCAPED_PIPE_SENTINEL, "|").trim());
}

function parseTableLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  if (start + 1 >= lines.length) return null;
  const header = lines[start];
  const delim = lines[start + 1];
  if (!header.includes("|") || !TABLE_DELIM_REGEX.test(delim)) return null;

  const alignments: TableAlignment[] = splitTableRow(delim).map((cell) => {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    if (left) return "left";
    return null;
  });

  const rows: string[][] = [splitTableRow(header)];
  let i = start + 2;
  while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
    rows.push(splitTableRow(lines[i]));
    i++;
  }

  return { block: { type: "table", alignments, rows }, next: i };
}

// -- Paragraph ----------------------------------------------------------------

function isBlockBoundary(line: string): boolean {
  return (
    line.trim() === "" ||
    line.trim() === "$$" ||
    line.trimStart().startsWith("```") ||
    BLOCKQUOTE_LINE_REGEX.test(line) ||
    HEADING_LINE_REGEX.test(line) ||
    UNORDERED_ITEM_REGEX.test(line) ||
    ORDERED_ITEM_REGEX.test(line) ||
    TABLE_DELIM_REGEX.test(line) ||
    isHrLine(line)
  );
}

function parseParagraphLines(lines: string[], start: number): BlockParseResult {
  if (lines[start].trim() === "") {
    return { block: null, next: start + 1 };
  }
  const paraLines: string[] = [];
  let i = start;
  while (i < lines.length && !isBlockBoundary(lines[i])) {
    paraLines.push(lines[i]);
    i++;
  }
  if (i === start) {
    // The line is a boundary no earlier parser accepted (e.g. a table
    // delimiter with no header above it). Consume exactly one line as text —
    // returning `next: start` here would stall parseBlocks forever.
    return { block: null, next: start + 1 };
  }
  return {
    block:
      paraLines.length > 0
        ? {
            // Preserve single newlines inside a paragraph (remark-breaks
            // parity) — RNText renders \n as a visual line break.
            type: "paragraph",
            segments: parseInline(paraLines.join("\n")),
          }
        : null,
    next: i,
  };
}

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const result =
      parseMathBlockLines(lines, i) ??
      parseCodeBlockLines(lines, i) ??
      parseHrLine(lines, i) ??
      parseHeadingLine(lines, i) ??
      parseTableLines(lines, i) ??
      parseBlockquoteLines(lines, i) ??
      parseListLines(lines, i) ??
      parseParagraphLines(lines, i);

    if (result.block) {
      blocks.push(result.block);
    }
    // Termination contract: every parser either consumes ≥1 line or returns
    // null with next ≥ start+1 (parseParagraphLines handles the
    // boundary-nobody-accepts case). If this invariant breaks, the loop
    // stalls — the regression tests pin it.
    i = result.next;
  }

  return blocks;
}

// -- Key helpers --------------------------------------------------------------

function segmentKey(seg: InlineSegment, idx: number): string {
  const label = seg.type === "image" ? seg.url : seg.text;
  return `${seg.type}-${idx}-${label.slice(0, 12)}`;
}

function blockKey(block: Block, idx: number): string {
  if (block.type === "codeBlock") return `cb-${idx}-${block.language}`;
  if (block.type === "hr") return `hr-${idx}`;
  return `${block.type}-${idx}`;
}

function listItemKey(item: ListItem, idx: number): string {
  return `li-${idx}-${item.blocks[0]?.type ?? "empty"}`;
}

export type { Block, InlineSegment, ListItem, TableAlignment };
export {
  blockKey,
  decodeEntities,
  listItemKey,
  parseBlocks,
  parseInline,
  segmentKey,
};
