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
  type Block,
  blockKey,
  decodeEntities,
  type InlineSegment,
  type ListItem,
  listItemKey,
  parseBlocks,
  repairStreamingMarkdown,
  segmentKey,
  type TableAlignment,
} from "@/components/ui/markdown-parser";
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

export interface MarkdownRendererProps {
  content: string;
  /**
   * While streaming, incomplete markdown is repaired before parsing (unclosed
   * fences/bold/etc.) so literal markers never flash mid-token.
   */
  isStreaming?: boolean;
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

  // Table cells are positional data with no natural identity, so stable keys
  // are derived from positions up front — outside JSX — keeping the render
  // map free of raw array indices.
  const columns = alignments.map((align, i) => ({
    id: `col-${i}`,
    align: align ?? null,
  }));
  const headerRow = header.map((value, i) => ({ id: `h-${i}`, value }));
  const bodyRows = body.map((cells, i) => ({
    id: `row-${i}`,
    cells: columns.map((col, c) => ({
      id: `${col.id}-${c}`,
      value: cells[c] ?? "",
      align: col.align,
    })),
  }));

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
        {headerRow.map((cell, i) => (
          <View
            key={cell.id}
            style={{ flex: 1, paddingHorizontal: 10, paddingVertical: 8 }}
          >
            <TableCellText value={cell.value} bold align={columns[i].align} />
          </View>
        ))}
      </View>
      {/* Body rows */}
      {bodyRows.map((row) => (
        <View
          key={row.id}
          style={{
            flexDirection: "row",
            borderTopWidth: 1,
            borderTopColor: "rgba(63,63,70,0.5)",
          }}
        >
          {row.cells.map((cell) => (
            <View
              key={cell.id}
              style={{ flex: 1, paddingHorizontal: 10, paddingVertical: 8 }}
            >
              <TableCellText value={cell.value} align={cell.align} />
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
