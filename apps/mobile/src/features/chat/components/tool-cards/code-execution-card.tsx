import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  ScrollView,
  Text as RNText,
  View,
} from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  CheckmarkCircle01Icon,
  Cancel01Icon,
  Copy01Icon,
  Tick02Icon,
  ArrowDown01Icon,
  CodeIcon,
  Clock01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { THEME } from "../code-block/syntax-theme";

// -- Constants ----------------------------------------------------------------

const COLORS = {
  cardBg: "#171920",
  headerBg: "#181825",
  headerBorder: "#313244",
  codeBg: THEME.background,
  codeHeaderBg: THEME.headerBg,
  codeHeaderBorder: THEME.headerBorder,
  outputBg: "#1a1a2e",
  errorBg: "#2d1b1b",
  errorBorder: "#7f1d1d",
  errorText: "#f87171",
  muted: "#71717a",
  dimmed: "#52525b",
  text: "#e4e4e7",
  subText: "#a1a1aa",
  runningColor: "#60a5fa",
  successColor: "#34d399",
  errorColor: "#f87171",
  divider: "rgba(255,255,255,0.08)",
  toggleText: "#60a5fa",
} as const;

const FONT = {
  mono: "RobotoMono_400Regular",
} as const;

const MAX_VISIBLE_LINES = 10;

// -- Types --------------------------------------------------------------------

export interface CodeExecutionData {
  status: "running" | "success" | "error";
  language?: string;
  code?: string;
  output?: string;
  error?: string;
  executionTime?: number;
}

interface CodeExecutionCardProps {
  toolData: CodeExecutionData;
}

// -- Spinner ------------------------------------------------------------------

function SpinnerIcon({ size, color }: { size: number; color: string }) {
  const rotation = useSharedValue(0);

  useEffect(() => {
    rotation.value = withRepeat(withTiming(360, { duration: 900 }), -1, false);
  }, [rotation]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  return (
    <Reanimated.View style={animatedStyle}>
      <View
        style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          borderWidth: 2,
          borderColor: color,
          borderTopColor: "transparent",
        }}
      />
    </Reanimated.View>
  );
}

// -- Status badge -------------------------------------------------------------

function StatusBadge({ status }: { status: CodeExecutionData["status"] }) {
  if (status === "running") {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 5,
          backgroundColor: "rgba(96,165,250,0.12)",
          borderRadius: 12,
          paddingHorizontal: 8,
          paddingVertical: 3,
        }}
      >
        <SpinnerIcon size={10} color={COLORS.runningColor} />
        <Text
          style={{
            fontSize: 10,
            color: COLORS.runningColor,
            fontWeight: "600",
          }}
        >
          Running
        </Text>
      </View>
    );
  }

  if (status === "success") {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 5,
          backgroundColor: "rgba(52,211,153,0.12)",
          borderRadius: 12,
          paddingHorizontal: 8,
          paddingVertical: 3,
        }}
      >
        <AppIcon icon={CheckmarkCircle01Icon} size={10} color={COLORS.successColor} />
        <Text
          style={{
            fontSize: 10,
            color: COLORS.successColor,
            fontWeight: "600",
          }}
        >
          Success
        </Text>
      </View>
    );
  }

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 5,
        backgroundColor: "rgba(248,113,113,0.12)",
        borderRadius: 12,
        paddingHorizontal: 8,
        paddingVertical: 3,
      }}
    >
      <AppIcon icon={Cancel01Icon} size={10} color={COLORS.errorColor} />
      <Text
        style={{
          fontSize: 10,
          color: COLORS.errorColor,
          fontWeight: "600",
        }}
      >
        Error
      </Text>
    </View>
  );
}

// -- Copy button --------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
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
    await Clipboard.setStringAsync(text);
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
  }, [copied, text, fadeAnim]);

  return (
    <Pressable
      onPress={handleCopy}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingVertical: 5,
        paddingHorizontal: 8,
        backgroundColor: "rgba(255,255,255,0.06)",
        borderRadius: 8,
      }}
      hitSlop={6}
    >
      <Animated.View style={{ opacity: fadeAnim }}>
        <AppIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={12}
          color={copied ? COLORS.successColor : COLORS.muted}
        />
      </Animated.View>
      <Text
        style={{
          fontSize: 10,
          color: copied ? COLORS.successColor : COLORS.muted,
          fontWeight: "500",
        }}
      >
        {copied ? "Copied" : "Copy Output"}
      </Text>
    </Pressable>
  );
}

// -- Animated chevron ---------------------------------------------------------

function AnimatedChevron({ isExpanded }: { isExpanded: boolean }) {
  const rotation = useSharedValue(0);

  useEffect(() => {
    rotation.value = withTiming(isExpanded ? 180 : 0, { duration: 200 });
  }, [isExpanded, rotation]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  return (
    <Reanimated.View style={animatedStyle}>
      <AppIcon icon={ArrowDown01Icon} size={12} color={COLORS.dimmed} />
    </Reanimated.View>
  );
}

// -- Code snippet section -----------------------------------------------------

function CodeSnippet({
  code,
  language,
}: {
  code: string;
  language?: string;
}) {
  const lines = code.split("\n");
  const trimmedLines =
    lines.length > 0 && lines[lines.length - 1] === ""
      ? lines.slice(0, -1)
      : lines;

  const [showFull, setShowFull] = useState(false);

  const displayLines = showFull
    ? trimmedLines
    : trimmedLines.slice(0, MAX_VISIBLE_LINES);

  const hasMore = trimmedLines.length > MAX_VISIBLE_LINES;

  return (
    <View
      style={{
        backgroundColor: COLORS.codeBg,
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      {/* Code header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: 10,
          paddingVertical: 5,
          backgroundColor: COLORS.codeHeaderBg,
          borderBottomWidth: 1,
          borderBottomColor: COLORS.codeHeaderBorder,
        }}
      >
        <RNText
          style={{
            fontFamily: FONT.mono,
            fontSize: 10,
            color: COLORS.muted,
            textTransform: "lowercase",
          }}
        >
          {language ?? "code"}
        </RNText>
        <Text style={{ fontSize: 10, color: COLORS.dimmed }}>
          {trimmedLines.length} lines
        </Text>
      </View>

      {/* Code body */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: 10, paddingVertical: 8 }}
        nestedScrollEnabled
      >
        <View>
          {displayLines.map((line, idx) => (
            <RNText
              key={`line-${idx}`}
              style={{
                fontFamily: FONT.mono,
                fontSize: 12,
                lineHeight: 19,
                color: THEME.plain,
              }}
            >
              {line || " "}
            </RNText>
          ))}
          {!showFull && hasMore && (
            <RNText
              style={{
                fontFamily: FONT.mono,
                fontSize: 12,
                lineHeight: 19,
                color: COLORS.dimmed,
              }}
            >
              {"  "}...
            </RNText>
          )}
        </View>
      </ScrollView>

      {/* Toggle */}
      {hasMore && (
        <Pressable
          onPress={() => setShowFull((v) => !v)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            paddingHorizontal: 10,
            paddingVertical: 6,
            borderTopWidth: 1,
            borderTopColor: COLORS.codeHeaderBorder,
          }}
          hitSlop={4}
        >
          <Text
            style={{
              fontSize: 10,
              color: COLORS.toggleText,
              fontWeight: "500",
            }}
          >
            {showFull
              ? "Show less"
              : `Show full code (${trimmedLines.length} lines)`}
          </Text>
          <AnimatedChevron isExpanded={showFull} />
        </Pressable>
      )}
    </View>
  );
}

// -- Code execution card ------------------------------------------------------

export function CodeExecutionCard({ toolData }: CodeExecutionCardProps) {
  const { status, language, code, output, error, executionTime } = toolData;

  const hasCode = !!code?.trim();
  const hasOutput = !!output?.trim();
  const hasError = !!error?.trim();

  const [codeExpanded, setCodeExpanded] = useState(false);

  const toggleCode = useCallback(() => {
    setCodeExpanded((v) => !v);
  }, []);

  return (
    <View
      style={{
        backgroundColor: COLORS.cardBg,
        borderRadius: 16,
        overflow: "hidden",
        borderWidth: 1,
        borderColor: COLORS.divider,
        marginVertical: 4,
      }}
    >
      {/* Header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: 14,
          paddingVertical: 10,
          backgroundColor: COLORS.headerBg,
          borderBottomWidth: 1,
          borderBottomColor: COLORS.headerBorder,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <View
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              backgroundColor: "rgba(96,165,250,0.12)",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={CodeIcon} size={14} color={COLORS.runningColor} />
          </View>
          <Text
            style={{ fontSize: 13, fontWeight: "600", color: COLORS.text }}
          >
            Code Execution
          </Text>
        </View>
        <StatusBadge status={status} />
      </View>

      <View style={{ padding: 12, gap: 10 }}>
        {/* Code snippet section */}
        {hasCode && (
          <View style={{ gap: 6 }}>
            <Pressable
              onPress={toggleCode}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              }}
              hitSlop={4}
            >
              <Text
                style={{
                  fontSize: 11,
                  color: COLORS.subText,
                  fontWeight: "500",
                  flex: 1,
                }}
              >
                Code
              </Text>
              <AnimatedChevron isExpanded={codeExpanded} />
            </Pressable>
            {codeExpanded && (
              <CodeSnippet code={code as string} language={language} />
            )}
          </View>
        )}

        {/* Divider between code and output */}
        {hasCode && (hasOutput || hasError) && (
          <View
            style={{ height: 1, backgroundColor: COLORS.divider }}
          />
        )}

        {/* Output section */}
        {hasOutput && (
          <View style={{ gap: 6 }}>
            <Text
              style={{
                fontSize: 11,
                color: COLORS.subText,
                fontWeight: "500",
              }}
            >
              Output
            </Text>
            <ScrollView
              style={{ maxHeight: 200 }}
              nestedScrollEnabled
              showsVerticalScrollIndicator={false}
            >
              <View
                style={{
                  backgroundColor: COLORS.outputBg,
                  borderRadius: 8,
                  padding: 10,
                }}
              >
                <RNText
                  style={{
                    fontFamily: FONT.mono,
                    fontSize: 12,
                    lineHeight: 19,
                    color: THEME.plain,
                  }}
                >
                  {output}
                </RNText>
              </View>
            </ScrollView>
          </View>
        )}

        {/* Error section */}
        {hasError && (
          <View style={{ gap: 6 }}>
            <Text
              style={{
                fontSize: 11,
                color: COLORS.errorText,
                fontWeight: "500",
              }}
            >
              Error
            </Text>
            <View
              style={{
                backgroundColor: COLORS.errorBg,
                borderRadius: 8,
                padding: 10,
                borderWidth: 1,
                borderColor: COLORS.errorBorder,
              }}
            >
              <RNText
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 12,
                  lineHeight: 19,
                  color: COLORS.errorText,
                }}
              >
                {error}
              </RNText>
            </View>
          </View>
        )}

        {/* Footer */}
        {(executionTime != null || hasOutput) && (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: 2,
            }}
          >
            {executionTime != null ? (
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
              >
                <AppIcon icon={Clock01Icon} size={11} color={COLORS.dimmed} />
                <Text style={{ fontSize: 10, color: COLORS.dimmed }}>
                  {executionTime < 1000
                    ? `${executionTime}ms`
                    : `${(executionTime / 1000).toFixed(2)}s`}
                </Text>
              </View>
            ) : (
              <View />
            )}
            {hasOutput && <CopyButton text={output as string} />}
          </View>
        )}
      </View>
    </View>
  );
}
