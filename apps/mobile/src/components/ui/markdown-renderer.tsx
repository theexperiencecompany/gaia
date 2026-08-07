import * as Linking from "expo-linking";
import { memo, useCallback, useState } from "react";
import { Text as RNText, View } from "react-native";
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

interface MarkdownRendererProps {
  content: string;
}

type InlineSegment =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "italic"; text: string }
  | { type: "boldItalic"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; url: string }
  | { type: "strikethrough"; text: string }
  | { type: "mathInline"; text: string };

type Block =
  | { type: "paragraph"; segments: InlineSegment[] }
  | { type: "heading"; level: number; segments: InlineSegment[] }
  | { type: "codeBlock"; language: string; code: string }
  | { type: "blockquote"; segments: InlineSegment[] }
  | { type: "unorderedList"; items: InlineSegment[][] }
  | { type: "orderedList"; items: InlineSegment[][] }
  | { type: "hr" }
  | { type: "mathBlock"; code: string };

// -- Parsing ------------------------------------------------------------------

function segmentFromMatch(match: RegExpExecArray): InlineSegment | null {
  if (match[2] && match[3]) {
    return { type: "link", text: match[2], url: match[3] };
  }
  if (match[4] || match[5]) {
    return { type: "boldItalic", text: match[4] || match[5] };
  }
  if (match[6] || match[7]) {
    return { type: "bold", text: match[6] || match[7] };
  }
  if (match[8] || match[9]) {
    return { type: "italic", text: match[8] || match[9] };
  }
  if (match[10]) {
    return { type: "strikethrough", text: match[10] };
  }
  if (match[11]) {
    return { type: "mathInline", text: match[11] };
  }
  if (match[12]) {
    return { type: "code", text: match[12] };
  }
  return null;
}

function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  // Order matters: bold-italic before bold before italic; $...$ before backtick
  const inlineRegex =
    /(\[([^\]]+)\]\(([^)]+)\)|\*\*\*(.+?)\*\*\*|___(.+?)___|\*\*(.+?)\*\*|__(.+?)__|_(.+?)_|\*(.+?)\*|~~(.+?)~~|\$(.+?)\$|`([^`]+)`)/g;

  let lastIndex = 0;
  let match = inlineRegex.exec(text);

  while (match !== null) {
    // Push preceding plain text
    if (match.index > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }

    const segment = segmentFromMatch(match);
    if (segment) {
      segments.push(segment);
    }

    lastIndex = match.index + match[0].length;
    match = inlineRegex.exec(text);
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }

  if (segments.length === 0) {
    segments.push({ type: "text", text });
  }

  return segments;
}

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

function parseHeadingLine(
  lines: string[],
  start: number,
): BlockParseResult | null {
  const headingMatch = lines[start].match(/^(#{1,6})\s+(.+)/);
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

function parseBlockquoteLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  if (!lines[start].trimStart().startsWith("> ")) return null;
  const quoteLines: string[] = [];
  let i = start;
  while (i < lines.length && lines[i].trimStart().startsWith("> ")) {
    quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
    i++;
  }
  return {
    block: { type: "blockquote", segments: parseInline(quoteLines.join(" ")) },
    next: i,
  };
}

function parseListLines(
  lines: string[],
  start: number,
): BlockParseResult | null {
  const unordered = /^\s*[-*+]\s+/;
  const ordered = /^\s*\d+[.)]\s+/;
  const matcher = unordered.test(lines[start])
    ? unordered
    : ordered.test(lines[start])
      ? ordered
      : null;
  if (!matcher) return null;
  const items: InlineSegment[][] = [];
  let i = start;
  while (i < lines.length && matcher.test(lines[i])) {
    items.push(parseInline(lines[i].replace(matcher, "")));
    i++;
  }
  return {
    block: {
      type: matcher === unordered ? "unorderedList" : "orderedList",
      items,
    },
    next: i,
  };
}

function isBlockBoundary(line: string): boolean {
  return (
    line.trim() === "" ||
    line.trim() === "$$" ||
    line.trimStart().startsWith("```") ||
    line.trimStart().startsWith("> ") ||
    /^#{1,6}\s+/.test(line) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    isHrLine(line)
  );
}

function parseParagraphLines(lines: string[], start: number): BlockParseResult {
  // Empty line: consume without producing a block.
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
        ? { type: "paragraph", segments: parseInline(paraLines.join(" ")) }
        : null,
    next: i,
  };
}

function parseMarkdown(raw: string): Block[] {
  const blocks: Block[] = [];
  const lines = raw.split("\n");
  let i = 0;

  while (i < lines.length) {
    // Order matters and mirrors the original precedence.
    const result =
      parseMathBlockLines(lines, i) ??
      parseCodeBlockLines(lines, i) ??
      parseHrLine(lines, i) ??
      parseHeadingLine(lines, i) ??
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
  return `${seg.type}-${idx}-${seg.text.slice(0, 12)}`;
}

function blockKey(block: Block, idx: number): string {
  if (block.type === "codeBlock") return `cb-${idx}-${block.language}`;
  if (block.type === "hr") return `hr-${idx}`;
  return `${block.type}-${idx}`;
}

function listItemKey(item: InlineSegment[], idx: number): string {
  return `li-${idx}-${item[0]?.text.slice(0, 12)}`;
}

// -- Rendering components -----------------------------------------------------

function InlineContent({ segments }: { segments: InlineSegment[] }) {
  const { fontSize } = useResponsive();
  const handleLinkPress = useCallback((url: string) => {
    Linking.openURL(url);
  }, []);

  return (
    <RNText
      style={{
        color: COLORS.text,
        fontSize: fontSize.base,
        lineHeight: Math.round(fontSize.base * 1.5),
      }}
    >
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
    1: responsiveFontSize["3xl"], // 30px
    2: responsiveFontSize["2xl"], // 24px
    3: responsiveFontSize.xl, // 20px
    4: responsiveFontSize.lg, // 18px
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
    1: 16,
    2: 12,
    3: 8,
    4: 8,
    5: 4,
    6: 4,
  };
  const fontSize = sizeMap[level] ?? responsiveFontSize.base;
  const marginTop = marginTopMap[level] ?? 8;
  const marginBottom = marginBottomMap[level] ?? 4;

  return (
    <View style={{ marginTop, marginBottom }}>
      <RNText
        style={{
          color: COLORS.text,
          fontSize,
          fontWeight: "700",
          lineHeight: Math.round(fontSize * 1.25),
        }}
      >
        {segments.map((seg, idx) => {
          const key = segmentKey(seg, idx);
          switch (seg.type) {
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
                  onPress={() => Linking.openURL(seg.url)}
                >
                  {seg.text}
                </RNText>
              );
            default:
              return <RNText key={key}>{seg.text}</RNText>;
          }
        })}
      </RNText>
    </View>
  );
}

function BlockquoteBlock({ segments }: { segments: InlineSegment[] }) {
  const { fontSize } = useResponsive();
  const handleLinkPress = useCallback((url: string) => {
    Linking.openURL(url);
  }, []);

  return (
    <View
      style={{
        borderLeftWidth: 3,
        borderLeftColor: COLORS.blockquoteBorder,
        paddingLeft: 12,
        paddingVertical: 6,
        marginVertical: 6,
        backgroundColor: "rgba(63,63,70,0.35)",
      }}
    >
      <RNText
        style={{
          color: COLORS.muted,
          fontSize: fontSize.base,
          lineHeight: Math.round(fontSize.base * 1.5),
          fontStyle: "italic",
        }}
      >
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
            case "strikethrough":
              return (
                <RNText
                  key={key}
                  style={{ textDecorationLine: "line-through" }}
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
            default:
              return <RNText key={key}>{seg.text}</RNText>;
          }
        })}
      </RNText>
    </View>
  );
}

function ListBlock({
  ordered,
  items,
}: {
  ordered: boolean;
  items: InlineSegment[][];
}) {
  const { fontSize } = useResponsive();
  return (
    <View style={{ marginVertical: 4, paddingLeft: 16 }}>
      {items.map((item, idx) => (
        <View
          key={listItemKey(item, idx)}
          style={{ flexDirection: "row", marginBottom: 8, paddingRight: 8 }}
        >
          {ordered ? (
            <RNText
              style={{
                color: COLORS.muted,
                fontSize: fontSize.base,
                lineHeight: Math.round(fontSize.base * 1.5),
                width: 24,
              }}
            >
              {`${idx + 1}.`}
            </RNText>
          ) : (
            <View
              style={{
                width: 16,
                alignItems: "center",
                paddingTop: 8,
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
            <InlineContent segments={item} />
          </View>
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
        marginVertical: 28,
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

// -- Main component -----------------------------------------------------------

function MarkdownRendererInner({ content }: MarkdownRendererProps) {
  if (!content || content.trim() === "") {
    return null;
  }

  const blocks = parseMarkdown(content);

  if (blocks.length === 0) {
    return null;
  }

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
                  marginBottom: idx < blocks.length - 1 ? 16 : 0,
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
          case "unorderedList":
            return <ListBlock key={key} ordered={false} items={block.items} />;
          case "orderedList":
            return <ListBlock key={key} ordered={true} items={block.items} />;
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

const MarkdownRenderer = memo(MarkdownRendererInner);

export type { MarkdownRendererProps };
export { MarkdownRenderer };
