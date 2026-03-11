import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { Button, Card, Chip } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Text as RNText, ScrollView, View } from "react-native";
import { AppIcon, Copy01Icon, Tick02Icon } from "@/components/icons";
import { THEME } from "./syntax-theme";
import { tokenizeLine } from "./tokenizer";

// -- Constants ----------------------------------------------------------------

const COLORS = {
  muted: "#a1a1aa",
  blockBg: THEME.background,
  blockHeaderBg: THEME.headerBg,
  blockHeaderBorder: THEME.headerBorder,
  codeBg: "#27272a",
  codeText: "#e4e4e7",
} as const;

const FONT = {
  mono: "RobotoMono_400Regular",
} as const;

// -- Types --------------------------------------------------------------------

export interface CodeBlockProps {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
}

export interface InlineCodeProps {
  children: string;
}

// -- InlineCode ---------------------------------------------------------------

export function InlineCode({ children }: InlineCodeProps) {
  return (
    <RNText
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
      {children}
    </RNText>
  );
}

// -- Copy button --------------------------------------------------------------

function CopyButton({ code }: { code: string }) {
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
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
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
    <Button variant="ghost" size="sm" isIconOnly onPress={handleCopy}>
      <Animated.View style={{ opacity: fadeAnim }}>
        <AppIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={14}
          color={copied ? "#34c759" : "#71717a"}
        />
      </Animated.View>
    </Button>
  );
}

// -- SyntaxLine ---------------------------------------------------------------

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

// -- CodeBlock ----------------------------------------------------------------

export function CodeBlock({
  code,
  language,
  showLineNumbers = false,
}: CodeBlockProps) {
  const lines = code.split("\n");
  const displayLines =
    lines.length > 0 && lines[lines.length - 1] === ""
      ? lines.slice(0, -1)
      : lines;
  const lang = language || "code";
  const lineNumberWidth = showLineNumbers
    ? String(displayLines.length).length * 8 + 12
    : 0;

  return (
    <Card
      style={{
        backgroundColor: COLORS.blockBg,
        borderRadius: 8,
        marginVertical: 6,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <Card.Header
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
        <Chip variant="soft" color="default" size="sm" animation="disable-all">
          <Chip.Label
            style={{
              fontFamily: FONT.mono,
              fontSize: 11,
              textTransform: "lowercase",
            }}
          >
            {lang}
          </Chip.Label>
        </Chip>
        <CopyButton code={code} />
      </Card.Header>

      {/* Code body — horizontal scroll for long lines */}
      <Card.Body style={{ padding: 0 }}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ padding: 12 }}
        >
          <View>
            {displayLines.map((line, lineIdx) => {
              const lineKey = `line-${lineIdx}`;
              return (
                <View
                  key={lineKey}
                  style={{ flexDirection: "row", alignItems: "flex-start" }}
                >
                  {showLineNumbers ? (
                    <RNText
                      style={{
                        fontFamily: FONT.mono,
                        fontSize: 13,
                        lineHeight: 20,
                        color: THEME.gutterText,
                        width: lineNumberWidth,
                        textAlign: "right",
                        marginRight: 12,
                        userSelect: "none",
                      }}
                    >
                      {lineIdx + 1}
                    </RNText>
                  ) : null}
                  <SyntaxLine line={line} language={language ?? ""} />
                </View>
              );
            })}
          </View>
        </ScrollView>
      </Card.Body>
    </Card>
  );
}
