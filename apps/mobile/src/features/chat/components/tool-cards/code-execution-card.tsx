import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { Spinner } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  Text as RNText,
  ScrollView,
  View,
} from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowDown01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  Clock01Icon,
  CodeIcon,
  Copy01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";
import { THEME } from "../code-block/syntax-theme";

// -- Constants ----------------------------------------------------------------

const COLORS = {
  codeBg: THEME.background,
  codeHeaderBg: THEME.headerBg,
  codeHeaderBorder: THEME.headerBorder,
  outputBg: "#18181b",
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
  toggleText: "#60a5fa",
} as const;

const FONT = {
  mono: "AnonymousPro_400Regular",
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

// -- Status badge -------------------------------------------------------------

function StatusBadge({ status }: { status: CodeExecutionData["status"] }) {
  if (status === "running") {
    return (
      <View className="flex-row items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-700/50">
        <Spinner size="sm" color="accent" />
        <Text className="text-xs font-semibold uppercase text-zinc-200">
          Running
        </Text>
      </View>
    );
  }

  if (status === "success") {
    return (
      <View className="flex-row items-center gap-1 px-2.5 py-1 rounded-full bg-green-500/15">
        <AppIcon
          icon={CheckmarkCircle01Icon}
          size={11}
          color={COLORS.successColor}
        />
        <Text className="text-xs font-semibold uppercase text-green-400">
          Success
        </Text>
      </View>
    );
  }

  return (
    <View className="flex-row items-center gap-1 px-2.5 py-1 rounded-full bg-red-500/15">
      <AppIcon icon={Cancel01Icon} size={11} color={COLORS.errorColor} />
      <Text className="text-xs font-semibold uppercase text-red-400">
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

function CodeSnippet({ code, language }: { code: string; language?: string }) {
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
        borderRadius: 16,
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
    <ToolCardShell>
      <ToolCardHeader
        icon={CodeIcon}
        iconColor={COLORS.runningColor}
        title="Code Execution"
        subtitle={language}
        trailing={<StatusBadge status={status} />}
      />

      <View style={{ gap: 12 }}>
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
            style={{ height: 1, backgroundColor: "rgba(255,255,255,0.08)" }}
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
                  borderRadius: 16,
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
                backgroundColor: "rgba(239,68,68,0.1)",
                borderRadius: 16,
                padding: 10,
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
    </ToolCardShell>
  );
}
