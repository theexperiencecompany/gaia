import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowDown01Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  CodeIcon,
  Copy01Icon,
  SourceCodeCircleIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { THEME } from "../code-block/syntax-theme";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "../../tool-data/primitives";

// ─── Types ────────────────────────────────────────────────────────────────────

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

// ─── Constants ────────────────────────────────────────────────────────────────

const MONO_FONT = "RobotoMono_400Regular";
const MAX_VISIBLE_LINES = 10;

const STDOUT_GREEN = "#86efac";
const STDERR_RED = "#fca5a5";

// ─── Status helpers ───────────────────────────────────────────────────────────

function statusPillClasses(status: CodeExecutionData["status"]): string {
  if (status === "running") return "bg-zinc-700";
  if (status === "error") return "bg-red-500/15";
  return "bg-green-500/15";
}

function statusPillTextClasses(status: CodeExecutionData["status"]): string {
  if (status === "running") return "text-zinc-200";
  if (status === "error") return "text-red-400";
  return "text-green-400";
}

function StatusIcon({ status }: { status: CodeExecutionData["status"] }) {
  if (status === "running") {
    return (
      <View className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent" />
    );
  }
  if (status === "error") {
    return <AppIcon icon={Cancel01Icon} size={12} color="#f87171" />;
  }
  return <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#4ade80" />;
}

function statusLabel(status: CodeExecutionData["status"]): string {
  if (status === "running") return "Running";
  if (status === "error") return "Error";
  return "Success";
}

// ─── Copy button ──────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (copied) return;
    await Clipboard.setStringAsync(text);
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [copied, text]);

  return (
    <Pressable
      onPress={handleCopy}
      className="flex-row items-center gap-1 rounded-lg bg-zinc-800 px-2 py-1"
      hitSlop={6}
    >
      <AppIcon
        icon={copied ? Tick02Icon : Copy01Icon}
        size={12}
        color={copied ? "#4ade80" : "#a1a1aa"}
      />
      <Text
        className={`text-[10px] font-medium ${copied ? "text-green-400" : "text-zinc-400"}`}
      >
        {copied ? "Copied" : "Copy"}
      </Text>
    </Pressable>
  );
}

// ─── Animated chevron ─────────────────────────────────────────────────────────

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
      <AppIcon icon={ArrowDown01Icon} size={12} color="#71717a" />
    </Reanimated.View>
  );
}

// ─── Code snippet section ─────────────────────────────────────────────────────

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
      className="rounded-xl overflow-hidden"
      style={{ backgroundColor: THEME.background }}
    >
      {/* Header */}
      <View
        className="flex-row items-center justify-between px-3 py-1.5"
        style={{ backgroundColor: THEME.headerBg }}
      >
        <Text
          style={{
            fontFamily: MONO_FONT,
            fontSize: 10,
            color: "#a1a1aa",
            textTransform: "lowercase",
          }}
        >
          {language ?? "code"}
        </Text>
        <Text className="text-[10px] text-zinc-500">
          {trimmedLines.length} lines
        </Text>
      </View>

      {/* Body */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 10 }}
        nestedScrollEnabled
      >
        <View>
          {displayLines.map((line, idx) => (
            <Text
              key={`line-${idx}`}
              style={{
                fontFamily: MONO_FONT,
                fontSize: 12,
                lineHeight: 19,
                color: THEME.plain,
              }}
            >
              {line || " "}
            </Text>
          ))}
          {!showFull && hasMore && (
            <Text
              style={{
                fontFamily: MONO_FONT,
                fontSize: 12,
                lineHeight: 19,
                color: "#71717a",
              }}
            >
              {"  "}...
            </Text>
          )}
        </View>
      </ScrollView>

      {/* Toggle */}
      {hasMore && (
        <Pressable
          onPress={() => setShowFull((v) => !v)}
          className="flex-row items-center gap-1 px-3 py-1.5"
          hitSlop={4}
        >
          <Text className="text-[10px] font-medium text-blue-400">
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

// ─── Main card ────────────────────────────────────────────────────────────────

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
        icon={SourceCodeCircleIcon}
        iconColor="#a1a1aa"
        title="Code Execution"
        trailing={
          <View
            className={`flex-row items-center gap-1.5 rounded-full px-2 py-1 ${statusPillClasses(status)}`}
          >
            <StatusIcon status={status} />
            <Text
              className={`text-[11px] font-medium ${statusPillTextClasses(status)}`}
            >
              {statusLabel(status)}
            </Text>
          </View>
        }
      />

      {/* Code section */}
      {hasCode && (
        <ToolCardInner className="mb-2">
          <Pressable
            onPress={toggleCode}
            className="flex-row items-center justify-between mb-2"
            hitSlop={4}
          >
            <View className="flex-row items-center gap-1.5">
              <AppIcon icon={CodeIcon} size={12} color="#a1a1aa" />
              <Text className="text-sm font-medium text-zinc-300">Code</Text>
            </View>
            <AnimatedChevron isExpanded={codeExpanded} />
          </Pressable>
          {codeExpanded && (
            <CodeSnippet code={code as string} language={language} />
          )}
        </ToolCardInner>
      )}

      {/* Output section */}
      {hasOutput && (
        <ToolCardInner className="mb-2">
          <View className="flex-row items-center justify-between mb-2">
            <Text className="text-sm font-medium text-zinc-300">Output</Text>
            <CopyButton text={output as string} />
          </View>
          <ScrollView
            style={{ maxHeight: 200 }}
            nestedScrollEnabled
            showsVerticalScrollIndicator={false}
          >
            <View
              className="rounded-xl overflow-hidden"
              style={{ backgroundColor: "#000" }}
            >
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ padding: 12 }}
              >
                <Text
                  style={{
                    fontFamily: MONO_FONT,
                    fontSize: 12,
                    lineHeight: 19,
                    color: STDOUT_GREEN,
                  }}
                >
                  {output}
                </Text>
              </ScrollView>
            </View>
          </ScrollView>
        </ToolCardInner>
      )}

      {/* Error section */}
      {hasError && (
        <ToolCardInner className="mb-2">
          <Text
            className="text-[10px] font-semibold text-red-400 mb-1"
            style={{ letterSpacing: 0.5 }}
          >
            ERROR
          </Text>
          <View
            className="rounded-xl overflow-hidden"
            style={{ backgroundColor: "#000" }}
          >
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ padding: 12 }}
            >
              <Text
                style={{
                  fontFamily: MONO_FONT,
                  fontSize: 12,
                  lineHeight: 19,
                  color: STDERR_RED,
                }}
              >
                {error}
              </Text>
            </ScrollView>
          </View>
        </ToolCardInner>
      )}

      {/* Footer */}
      {executionTime != null && (
        <View className="flex-row items-center gap-1 pt-1">
          <AppIcon icon={Clock01Icon} size={11} color="#71717a" />
          <Text className="text-[10px] text-zinc-500">
            {executionTime < 1000
              ? `${executionTime}ms`
              : `${(executionTime / 1000).toFixed(2)}s`}
          </Text>
        </View>
      )}
    </ToolCardShell>
  );
}
