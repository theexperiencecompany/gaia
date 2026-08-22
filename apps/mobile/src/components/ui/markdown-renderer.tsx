import * as Linking from "expo-linking";
import { memo, useCallback, useState } from "react";
import {
  Image,
  Text as RNText,
  type StyleProp,
  type TextStyle,
  View,
} from "react-native";
import { WebView } from "react-native-webview";
import {
  CodeBlock,
  InlineCode,
} from "@/features/chat/components/code-block/CodeBlock";
import { useResponsive } from "@/lib/responsive";

// -- Theme constants ----------------------------------------------------------

const COLORS = {
  text: "#ffffff",
  muted: "#a1a1aa",
  blockquoteBorder: "#3f3f46", // zinc-700
  hrColor: "#3f3f46",
  linkColor: "#00bbff",
} as const;

// -- Types --------------------------------------------------------------------

export interface MarkdownRendererProps {
  content: string;
  /**
   * While streaming, incomplete markdown is repaired before parsing (unclosed
   * fences/bold/etc.) so literal markers never flash mid-token.
   */
  isStreaming?: boolean;
}

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
  if (match[1]) return { type: "image", alt: match[2], url: match[3] };
  if (match[4] && match[5]) {
    return { type: "link", text: match[4], url: match[5] };
  }
  if (match[6] || match[7]) {
    return { type: "boldItalic", text: match[6] || match[7] };
  }
  if (match[8] || match[9]) {
    return { type: "bold", text: match[8] || match[9] };
  }
  if (match[10] || match[11]) {
    return { type: "italic", text: match[10] || match[11] };
  }
  if (match[12]) {
    return { type: "strikethrough", text: match[12] };
  }
  if (match[13]) {
    return { type: "mathInline", text: match[13] };
  }
  if (match[14]) {
    return { type: "code", text: match[14] };
  }
  return null;
}

// Order matters: image before link; bold-italic before bold before italic;
// $...$ before backtick.
const INLINE_REGEX = new RegExp(
  [
    /!\[([^\]]*)\]\(([^)]+)\)/.source, // 1-3 image
    /\[([^\]]+)\]\(([^)]+)\)/.source, // 4-5 link
    /\*\*\*([\s\S]+?)\*\*\*/.source, // 6 bold-italic ***
    /___([\s\S]+?)___/.source, // 7 bold-italic ___
    /\*\*([\s\S]+?)\*\*/.source, // 8 bold **
    /__([\s\S]+?)__/.source, // 9 bold __
    /(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])/.source, // 10 italic *
    /(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])/.source, // 11 italic _
    /~~([\s\S]+?)~~/.source, // 12 strikethrough
    /\$([^$\n]+?)\$/.source, // 13 math inline
    /`([^`\n]+)`/.source, // 14 code
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

// -- Rendering components -----------------------------------------------------

function useBodyTextStyle() {
  const { fontSize } = useResponsive();
  return {
    color: COLORS.text,
    fontSize: fontSize.base,
    lineHeight: Math.round(fontSize.base * 1.5),
  } as const;
}

function MarkdownImage({ url, alt }: { url: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  const bodyStyle = useBodyTextStyle();
  if (failed) {
    return (
      <RNText style={[bodyStyle, { color: COLORS.linkColor }]}>
        {alt || url}
      </RNText>
    );
  }
  return (
    <Image
      source={{ uri: url }}
      accessibilityLabel={alt}
      resizeMode="cover"
      style={{
        width: "100%",
        height: 180,
        borderRadius: 12,
        marginVertical: 6,
        backgroundColor: "#1c1c1f",
      }}
      onError={() => setFailed(true)}
    />
  );
}

function InlineContent({
  segments,
  style,
}: {
  segments: InlineSegment[];
  /** Applied to the root text node; nested segments inherit font/color. */
  style?: StyleProp<TextStyle>;
}) {
  const bodyStyle = useBodyTextStyle();
  const handleLinkPress = useCallback((url: string) => {
    void Linking.openURL(url);
  }, []);

  return (
    <RNText style={[bodyStyle, style]}>
      {segments.map((seg, idx) => {
        const key = segmentKey(seg, idx);
        switch (seg.type) {
          case "text":
            return <RNText key={key}>{seg.text}</RNText>;
          case "bold":
            return (
              <RNText key={key} style={{ fontWeight: "700" }}>
                {seg.text}
              </RNText>
            );
          case "italic":
            return (
              <RNText key={key} style={{ fontStyle: "italic" }}>
                {seg.text}
              </RNText>
            );
          case "boldItalic":
            return (
              <RNText
                key={key}
                style={{ fontWeight: "700", fontStyle: "italic" }}
              >
                {seg.text}
              </RNText>
            );
          case "code":
            return <InlineCode key={key}>{seg.text}</InlineCode>;
          case "link":
            return (
              <RNText
                key={key}
                style={{
                  color: COLORS.linkColor,
                  textDecorationLine: "underline",
                }}
                onPress={() => handleLinkPress(seg.url)}
              >
                {seg.text}
              </RNText>
            );
          case "image":
            return <MarkdownImage key={key} url={seg.url} alt={seg.alt} />;
          case "strikethrough":
            return (
              <RNText key={key} style={{ textDecorationLine: "line-through" }}>
                {seg.text}
              </RNText>
            );
          case "mathInline":
            return <MathBlock key={key} code={seg.text} inline />;
          default:
            return null;
        }
      })}
    </RNText>
  );
}

function HeadingBlock({
  level,
  segments,
}: {
  level: number;
  segments: InlineSegment[];
}) {
  const { fontSize: responsiveFontSize } = useResponsive();

  // Heading sizes mapped to design-system token scale
  const sizeMap: Record<number, number> = {
    1: responsiveFontSize["2xl"], // 24px — h1 in a chat bubble shouldn't be display-size
    2: responsiveFontSize.xl, // 20px
    3: responsiveFontSize.lg, // 18px
    4: responsiveFontSize.base, // 16px
    5: responsiveFontSize.base, // 16px
    6: responsiveFontSize.sm, // 12px
  };
  const marginTopMap: Record<number, number> = {
    1: 24,
    2: 20,
    3: 16,
    4: 12,
    5: 8,
    6: 8,
  };
  const marginBottomMap: Record<number, number> = {
    1: 12,
    2: 10,
    3: 8,
    4: 6,
    5: 4,
    6: 4,
  };
  const fontSize = sizeMap[level] ?? responsiveFontSize.base;
  const marginTop = marginTopMap[level] ?? 8;
  const marginBottom = marginBottomMap[level] ?? 4;

  return (
    <View style={{ marginTop, marginBottom }}>
      <InlineContent
        segments={segments}
        style={{
          fontSize,
          fontWeight: "700",
          lineHeight: Math.round(fontSize * 1.25),
        }}
      />
    </View>
  );
}

function BlockquoteBlock({ segments }: { segments: InlineSegment[] }) {
  return (
    <View
      style={{
        borderLeftWidth: 3,
        borderLeftColor: COLORS.blockquoteBorder,
        paddingLeft: 12,
        paddingVertical: 6,
        marginVertical: 6,
        backgroundColor: "rgba(63,63,70,0.35)",
        borderRadius: 4,
      }}
    >
      <InlineContent
        segments={segments}
        style={{ color: COLORS.muted, fontStyle: "italic" }}
      />
    </View>
  );
}

function ListBlock({
  ordered,
  start,
  items,
}: {
  ordered: boolean;
  start: number;
  items: ListItem[];
}) {
  const bodyStyle = useBodyTextStyle();
  return (
    <View style={{ marginVertical: 4, paddingLeft: 8 }}>
      {items.map((item, idx) => {
        const marker = ordered ? `${start + idx}.` : null;
        return (
          <View
            key={listItemKey(item, idx)}
            style={{ flexDirection: "row", marginBottom: 6, paddingRight: 8 }}
          >
            {item.task ? (
              <View style={{ width: 24, paddingTop: 3 }}>
                {/* Checkbox drawn with views, not glyph text */}
                <View
                  style={{
                    width: 16,
                    height: 16,
                    borderRadius: 4,
                    borderWidth: 1.5,
                    borderColor: item.checked ? COLORS.linkColor : COLORS.muted,
                    backgroundColor: item.checked
                      ? COLORS.linkColor
                      : "transparent",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {item.checked ? (
                    <View
                      style={{
                        width: 8,
                        height: 4,
                        borderLeftWidth: 2,
                        borderBottomWidth: 2,
                        borderColor: "#000",
                        transform: [{ rotate: "-45deg" }, { translateY: -1 }],
                      }}
                    />
                  ) : null}
                </View>
              </View>
            ) : marker ? (
              <RNText style={{ ...bodyStyle, color: COLORS.muted, width: 24 }}>
                {marker}
              </RNText>
            ) : (
              <View
                style={{
                  width: 24,
                  alignItems: "center",
                  paddingTop: Math.round(bodyStyle.fontSize * 0.55),
                }}
              >
                <View
                  style={{
                    width: 4,
                    height: 4,
                    borderRadius: 2,
                    backgroundColor: COLORS.muted,
                  }}
                />
              </View>
            )}
            <View style={{ flex: 1 }}>
              <RenderBlocks blocks={item.blocks} />
            </View>
          </View>
        );
      })}
    </View>
  );
}

function TableCellText({
  value,
  bold,
  align,
}: {
  value: string;
  bold?: boolean;
  align: TableAlignment;
}) {
  const bodyStyle = useBodyTextStyle();
  return (
    <RNText
      style={[
        bodyStyle,
        bold ? { fontWeight: "600" } : null,
        { textAlign: align ?? "left" },
      ]}
    >
      {decodeEntities(value)}
    </RNText>
  );
}

function TableBlock({
  alignments,
  rows,
}: {
  alignments: TableAlignment[];
  rows: string[][];
}) {
  const [header, ...body] = rows;
  if (!header) return null;

  return (
    <View
      style={{
        marginVertical: 8,
        borderRadius: 12,
        overflow: "hidden",
        backgroundColor: "#1f1f23",
      }}
    >
      {/* Header row */}
      <View style={{ flexDirection: "row", backgroundColor: "#27272a" }}>
        {header.map((cell, col) => (
          <View
            // biome-ignore lint/suspicious/noArrayIndexKey: positional column identity; cell text can repeat
            key={`h-${col}`}
            style={{ flex: 1, paddingHorizontal: 10, paddingVertical: 8 }}
          >
            <TableCellText value={cell} bold align={alignments[col] ?? null} />
          </View>
        ))}
      </View>
      {/* Body rows */}
      {body.map((row, rowIdx) => (
        <View
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positional data with no stable identity
          key={`r-${rowIdx}`}
          style={{
            flexDirection: "row",
            borderTopWidth: 1,
            borderTopColor: "rgba(63,63,70,0.5)",
          }}
        >
          {header.map((_, col) => (
            <View
              // biome-ignore lint/suspicious/noArrayIndexKey: same positional column identity as the header
              key={`c-${rowIdx}-${col}`}
              style={{ flex: 1, paddingHorizontal: 10, paddingVertical: 8 }}
            >
              <TableCellText
                value={row[col] ?? ""}
                align={alignments[col] ?? null}
              />
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}

function HorizontalRule() {
  return (
    <View
      style={{
        height: 1,
        backgroundColor: COLORS.hrColor,
        marginVertical: 16,
      }}
    />
  );
}

// -- Mermaid and Math components ----------------------------------------------

function MermaidBlock({ code }: { code: string }) {
  const [height, setHeight] = useState(200);

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body { background: #1e1e2e; margin: 0; padding: 12px; font-family: sans-serif; }
    .mermaid { background: transparent; }
    svg { max-width: 100%; }
  </style>
</head>
<body>
  <div class="mermaid">${code.replace(/`/g, "\\`").replace(/<\/script>/g, "<\\/script>")}</div>
  <script>
    mermaid.initialize({
      theme: 'dark',
      startOnLoad: true,
      themeVariables: { background: '#1e1e2e', primaryColor: '#00bbff' }
    });
    setTimeout(() => {
      const h = document.body.scrollHeight;
      window.ReactNativeWebView.postMessage(JSON.stringify({ height: h }));
    }, 500);
  </script>
</body>
</html>`;

  return (
    <View
      style={{
        marginVertical: 8,
        borderRadius: 8,
        overflow: "hidden",
        backgroundColor: "#1e1e2e",
      }}
    >
      <WebView
        source={{ html }}
        style={{ height, backgroundColor: "#1e1e2e" }}
        scrollEnabled={false}
        onMessage={(event) => {
          try {
            const data = JSON.parse(event.nativeEvent.data);
            if (data.height) setHeight(Math.max(data.height, 100));
          } catch {
            /* ignore: web content may post non-JSON messages */
          }
        }}
        originWhitelist={["*"]}
        javaScriptEnabled
      />
    </View>
  );
}

function MathBlock({ code, inline }: { code: string; inline?: boolean }) {
  const [height, setHeight] = useState(inline ? 24 : 60);

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.js"></script>
  <style>
    body { background: transparent; margin: 0; padding: ${inline ? 0 : 8}px; font-size: 15px; color: #e4e4e7; }
    .katex { color: #e4e4e7; }
  </style>
</head>
<body>
  <div id="math"></div>
  <script defer>
    document.addEventListener("DOMContentLoaded", function() {
      try {
        katex.render(${JSON.stringify(code)}, document.getElementById("math"), {
          displayMode: ${!inline},
          throwOnError: false,
        });
        setTimeout(() => {
          window.ReactNativeWebView.postMessage(JSON.stringify({ height: document.body.scrollHeight }));
        }, 100);
      } catch(e) {
        document.getElementById("math").innerText = ${JSON.stringify(code)};
        window.ReactNativeWebView.postMessage(JSON.stringify({ height: document.body.scrollHeight }));
      }
    });
  </script>
</body>
</html>`;

  return (
    <WebView
      source={{ html }}
      style={{
        height,
        backgroundColor: "transparent",
        marginVertical: inline ? 0 : 4,
      }}
      scrollEnabled={false}
      onMessage={(event) => {
        try {
          const data = JSON.parse(event.nativeEvent.data);
          if (data.height) setHeight(Math.max(data.height, inline ? 20 : 40));
        } catch {
          /* ignore: web content may post non-JSON messages */
        }
      }}
      originWhitelist={["*"]}
      javaScriptEnabled
    />
  );
}

// -- Block dispatcher ---------------------------------------------------------

function RenderBlocks({ blocks }: { blocks: Block[] }) {
  return (
    <View>
      {blocks.map((block, idx) => {
        const key = blockKey(block, idx);
        switch (block.type) {
          case "paragraph":
            return (
              <View
                key={key}
                style={{
                  marginTop: 0,
                  marginBottom: idx < blocks.length - 1 ? 12 : 0,
                }}
              >
                <InlineContent segments={block.segments} />
              </View>
            );
          case "heading":
            return (
              <HeadingBlock
                key={key}
                level={block.level}
                segments={block.segments}
              />
            );
          case "codeBlock":
            if (block.language === "mermaid") {
              return <MermaidBlock key={key} code={block.code} />;
            }
            return (
              <CodeBlock
                key={key}
                language={block.language}
                code={block.code}
              />
            );
          case "blockquote":
            return <BlockquoteBlock key={key} segments={block.segments} />;
          case "list":
            return (
              <ListBlock
                key={key}
                ordered={block.ordered}
                start={block.start}
                items={block.items}
              />
            );
          case "table":
            return (
              <TableBlock
                key={key}
                alignments={block.alignments}
                rows={block.rows}
              />
            );
          case "hr":
            return <HorizontalRule key={key} />;
          case "mathBlock":
            return <MathBlock key={key} code={block.code} />;
          default:
            return null;
        }
      })}
    </View>
  );
}

// -- Main component -----------------------------------------------------------

function MarkdownRendererInner({
  content,
  isStreaming,
}: MarkdownRendererProps) {
  const source = isStreaming ? repairStreamingMarkdown(content) : content;
  if (!source || source.trim() === "") {
    return null;
  }

  const blocks = parseBlocks(source.split("\n"));

  if (blocks.length === 0) {
    return null;
  }

  return <RenderBlocks blocks={blocks} />;
}

const MarkdownRenderer = memo(MarkdownRendererInner);

export { MarkdownRenderer };
