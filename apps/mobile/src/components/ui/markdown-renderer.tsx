import * as Linking from "expo-linking";
import { memo, useCallback, useState } from "react";
import { Text as RNText, View } from "react-native";
import { WebView } from "react-native-webview";
import {
  CodeBlock,
  InlineCode,
} from "@/features/chat/components/code-block/CodeBlock";

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
      segments.push({ type: "mathInline", text: match[11] });
    } else if (match[12]) {
      segments.push({ type: "code", text: match[12] });
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

    // Display math block $$...$$
    if (line.trim() === "$$") {
      const mathLines: string[] = [];
      i++;
      while (i < lines.length && lines[i].trim() !== "$$") {
        mathLines.push(lines[i]);
        i++;
      }
      i++; // skip closing $$
      blocks.push({ type: "mathBlock", code: mathLines.join("\n") });
      continue;
    }

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
      lines[i].trim() !== "$$" &&
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
            return <InlineCode key={key}>{seg.text}</InlineCode>;
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
          } catch {}
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
        } catch {}
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

export { MarkdownRenderer };
export type { MarkdownRendererProps };
