import * as Clipboard from "expo-clipboard";
import * as Linking from "expo-linking";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  Text as RNText,
  ScrollView,
  View,
} from "react-native";
import { Copy01Icon, HugeiconsIcon, Tick02Icon } from "@/components/icons";
import { THEME } from "@/features/chat/components/code-block/syntax-theme";
import { tokenizeLine } from "@/features/chat/components/code-block/tokenizer";

// -- Theme constants ----------------------------------------------------------

const COLORS = {
  text: "#ffffff",
  muted: "#a1a1aa",
  accent: "#00bbff",
  codeBg: "#27272a", // zinc-800 (inline code)
  codeText: "#e4e4e7", // zinc-200
  blockBg: THEME.background, // #1e1e2e - code block background
  blockHeaderBg: THEME.headerBg, // #181825 - code block header
  blockHeaderBorder: THEME.headerBorder, // #313244 - header divider
  blockquoteBorder: "#3f3f46", // zinc-700
  hrColor: "#3f3f46",
  linkColor: "#00bbff",
} as const;

const FONT = {
  mono: "RobotoMono_400Regular",
  monoMedium: "RobotoMono_500Medium",
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
  | { type: "strikethrough"; text: string };

type Block =
  | { type: "paragraph"; segments: InlineSegment[] }
  | { type: "heading"; level: number; segments: InlineSegment[] }
  | { type: "codeBlock"; language: string; code: string }
  | { type: "blockquote"; segments: InlineSegment[] }
  | { type: "unorderedList"; items: InlineSegment[][] }
  | { type: "orderedList"; items: InlineSegment[][] }
  | { type: "hr" };

// -- Parsing ------------------------------------------------------------------

function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  // Order matters: bold-italic before bold before italic
  const inlineRegex =
    /(\[([^\]]+)\]\(([^)]+)\)|\*\*\*(.+?)\*\*\*|___(.+?)___|\*\*(.+?)\*\*|__(.+?)__|_(.+?)_|\*(.+?)\*|~~(.+?)~~|`([^`]+)`)/g;

  let lastIndex = 0;
  let match = inlineRegex.exec(text);

  while (match !== null) {
    // Push preceding plain text
    if (match.index > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }

    if (match[2] && match[3]) {
      segments.push({ type: "link", text: match[2], url: match[3] });
    } else if (match[4] || match[5]) {
      segments.push({ type: "boldItalic", text: match[4] || match[5] });
    } else if (match[6] || match[7]) {
      segments.push({ type: "bold", text: match[6] || match[7] });
    } else if (match[8] || match[9]) {
      segments.push({ type: "italic", text: match[8] || match[9] });
    } else if (match[10]) {
      segments.push({ type: "strikethrough", text: match[10] });
    } else if (match[11]) {
      segments.push({ type: "code", text: match[11] });
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

function parseMarkdown(raw: string): Block[] {
  const blocks: Block[] = [];
  const lines = raw.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.trimStart().startsWith("```")) {
      const language = line.trimStart().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "codeBlock", language, code: codeLines.join("\n") });
      continue;
    }

    // Horizontal rule
    if (/^(\s*[-*_]\s*){3,}$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        segments: parseInline(headingMatch[2]),
      });
      i++;
      continue;
    }

    // Blockquote
    if (line.trimStart().startsWith("> ")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith("> ")) {
        quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      blocks.push({
        type: "blockquote",
        segments: parseInline(quoteLines.join(" ")),
      });
      continue;
    }

    // Unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: InlineSegment[][] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(parseInline(lines[i].replace(/^\s*[-*+]\s+/, "")));
        i++;
      }
      blocks.push({ type: "unorderedList", items });
      continue;
    }

    // Ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: InlineSegment[][] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(parseInline(lines[i].replace(/^\s*\d+[.)]\s+/, "")));
        i++;
      }
      blocks.push({ type: "orderedList", items });
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: accumulate contiguous non-empty lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !lines[i].trimStart().startsWith("> ") &&
      !/^#{1,6}\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !/^(\s*[-*_]\s*){3,}$/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({
        type: "paragraph",
        segments: parseInline(paraLines.join(" ")),
      });
    }
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

// -- Rendering components -----------------------------------------------------

function InlineContent({ segments }: { segments: InlineSegment[] }) {
  const handleLinkPress = useCallback((url: string) => {
    Linking.openURL(url);
  }, []);

  return (
    <RNText style={{ color: COLORS.text, fontSize: 15, lineHeight: 22 }}>
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
            return (
              <RNText
                key={key}
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 13,
                  backgroundColor: COLORS.codeBg,
                  color: COLORS.codeText,
                  borderRadius: 4,
                  paddingHorizontal: 5,
                  paddingVertical: 1,
                }}
              >
                {seg.text}
              </RNText>
            );
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
          default:
            return null;
        }
      })}
    </RNText>
  );
}

function CodeBlockCopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const fadeAnim = useRef(new Animated.Value(1)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleCopy = useCallback(async () => {
    if (copied) return;
    await Clipboard.setStringAsync(code);
    setCopied(true);

    Animated.sequence([
      Animated.timing(fadeAnim, {
        toValue: 0.3,
        duration: 100,
        useNativeDriver: true,
      }),
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 150,
        useNativeDriver: true,
      }),
    ]).start();

    timerRef.current = setTimeout(() => setCopied(false), 2000);
  }, [copied, code, fadeAnim]);

  return (
    <Pressable onPress={handleCopy} style={{ padding: 6 }} hitSlop={8}>
      <Animated.View style={{ opacity: fadeAnim }}>
        <HugeiconsIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={14}
          color={copied ? "#34c759" : "#71717a"}
        />
      </Animated.View>
    </Pressable>
  );
}

function SyntaxLine({ line, language }: { line: string; language: string }) {
  const tokens = tokenizeLine(line, language || "text");
  return (
    <RNText
      style={{
        fontFamily: FONT.mono,
        fontSize: 13,
        lineHeight: 20,
        color: THEME.plain,
      }}
    >
      {tokens.map((token, tokenIdx) => {
        const tokenKey = `t-${tokenIdx}`;
        const color =
          token.type === "plain"
            ? THEME.plain
            : (THEME[token.type as keyof typeof THEME] ?? THEME.plain);
        return (
          <RNText
            key={tokenKey}
            style={{
              fontFamily: FONT.mono,
              fontSize: 13,
              color: typeof color === "string" ? color : THEME.plain,
            }}
          >
            {token.value}
          </RNText>
        );
      })}
    </RNText>
  );
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const lines = code.split("\n");
  // Strip trailing empty line that often appears after the closing ```
  const displayLines =
    lines.length > 0 && lines[lines.length - 1] === ""
      ? lines.slice(0, -1)
      : lines;
  const lang = language || "code";

  return (
    <View
      style={{
        backgroundColor: COLORS.blockBg,
        borderRadius: 8,
        marginVertical: 6,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          paddingHorizontal: 12,
          paddingVertical: 6,
          backgroundColor: COLORS.blockHeaderBg,
          borderBottomWidth: 1,
          borderBottomColor: COLORS.blockHeaderBorder,
        }}
      >
        <RNText
          style={{
            fontFamily: FONT.mono,
            fontSize: 11,
            color: COLORS.muted,
            textTransform: "lowercase",
          }}
        >
          {lang}
        </RNText>
        <CodeBlockCopyButton code={code} />
      </View>

      {/* Code body — horizontal scroll for long lines */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ padding: 12 }}
      >
        <View>
          {displayLines.map((line, lineIdx) => {
            const lineKey = `line-${lineIdx}`;
            return <SyntaxLine key={lineKey} line={line} language={language} />;
          })}
        </View>
      </ScrollView>
    </View>
  );
}

function HeadingBlock({
  level,
  segments,
}: {
  level: number;
  segments: InlineSegment[];
}) {
  const sizeMap: Record<number, number> = {
    1: 24,
    2: 21,
    3: 18,
    4: 16,
    5: 15,
    6: 14,
  };
  const fontSize = sizeMap[level] ?? 15;

  return (
    <View style={{ marginTop: level <= 2 ? 12 : 8, marginBottom: 4 }}>
      <RNText
        style={{
          color: COLORS.text,
          fontSize,
          fontWeight: "700",
          lineHeight: fontSize * 1.3,
        }}
      >
        {segments.map((seg, idx) => {
          const key = segmentKey(seg, idx);
          switch (seg.type) {
            case "code":
              return (
                <RNText
                  key={key}
                  style={{
                    fontFamily: FONT.mono,
                    fontSize: fontSize - 2,
                    backgroundColor: COLORS.codeBg,
                    color: COLORS.codeText,
                  }}
                >
                  {seg.text}
                </RNText>
              );
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
  return (
    <View
      style={{
        borderLeftWidth: 3,
        borderLeftColor: COLORS.blockquoteBorder,
        paddingLeft: 12,
        paddingVertical: 4,
        marginVertical: 6,
      }}
    >
      <RNText
        style={{
          color: COLORS.muted,
          fontSize: 15,
          lineHeight: 22,
          fontStyle: "italic",
        }}
      >
        {segments.map((seg, idx) => {
          const key = segmentKey(seg, idx);
          if (seg.type === "text") return <RNText key={key}>{seg.text}</RNText>;
          if (seg.type === "bold")
            return (
              <RNText key={key} style={{ fontWeight: "700" }}>
                {seg.text}
              </RNText>
            );
          if (seg.type === "code")
            return (
              <RNText
                key={key}
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 13,
                  backgroundColor: COLORS.codeBg,
                  color: COLORS.codeText,
                }}
              >
                {seg.text}
              </RNText>
            );
          return <RNText key={key}>{seg.text}</RNText>;
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
  return (
    <View style={{ marginVertical: 4, paddingLeft: 8 }}>
      {items.map((item, idx) => (
        <View
          key={`li-${idx}-${item[0]?.text.slice(0, 12)}`}
          style={{ flexDirection: "row", marginBottom: 3, paddingRight: 8 }}
        >
          <RNText
            style={{
              color: COLORS.muted,
              fontSize: 15,
              lineHeight: 22,
              width: ordered ? 24 : 16,
            }}
          >
            {ordered ? `${idx + 1}.` : "\u2022"}
          </RNText>
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
        marginVertical: 12,
      }}
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
              <View key={key} style={{ marginVertical: 2 }}>
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
          default:
            return null;
        }
      })}
    </View>
  );
}

const MarkdownRenderer = memo(MarkdownRendererInner);

export { MarkdownRenderer };
export type { MarkdownRendererProps };
