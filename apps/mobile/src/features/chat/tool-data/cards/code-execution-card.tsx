import type { CodeChartData, CodeData, CodeOutput } from "@gaia/shared";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  Text as RNText,
  ScrollView,
  View,
} from "react-native";
import {
  AppIcon,
  ArrowDown02Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  SourceCodeCircleIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { CodeBlock } from "@/features/chat/components/code-block/CodeBlock";
import {
  type ChartDisplayData,
  ChartItem,
} from "@/features/chat/tool-data/cards/chart-card";
import {
  SectionLabel,
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MONO_FONT = "AnonymousPro_400Regular";

const COLORS = {
  outputBg: "#000000cc",
  stdoutText: "#4ade80",
  resultsText: "#60a5fa",
  errorText: "#f87171",
  muted: "#71717a",
  accent: "#00bbff",
  success: "#34c759",
  failed: "#ff453a",
} as const;

// ---------------------------------------------------------------------------
// StatusChip — mirrors web CodeExecutionOutput status pill
// ---------------------------------------------------------------------------

interface StatusChipProps {
  status?: CodeData["status"];
  hasError: boolean;
}

function StatusChip({ status, hasError }: StatusChipProps) {
  if (status === "executing") {
    return (
      <View className="flex-row items-center gap-1.5 px-2 py-1 rounded-full bg-zinc-700/50">
        <View
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            backgroundColor: COLORS.accent,
          }}
        />
        <Text className="text-xs font-semibold uppercase text-zinc-200">
          Running
        </Text>
      </View>
    );
  }
  if (status === "error" || hasError) {
    return (
      <View className="flex-row items-center gap-1 px-2 py-1 rounded-full bg-red-500/15">
        <AppIcon icon={Cancel01Icon} size={11} color={COLORS.failed} />
        <Text className="text-xs font-semibold uppercase text-red-400">
          Failed
        </Text>
      </View>
    );
  }
  if (status === "completed" && !hasError) {
    return (
      <View className="flex-row items-center gap-1 px-2 py-1 rounded-full bg-green-500/15">
        <AppIcon
          icon={CheckmarkCircle02Icon}
          size={11}
          color={COLORS.success}
        />
        <Text className="text-xs font-semibold uppercase text-green-400">
          Success
        </Text>
      </View>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// CopyButton — mirrors web CopyButton (icon + state toggle)
// ---------------------------------------------------------------------------

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
      className="flex-row items-center gap-1 px-2 py-1 rounded-lg bg-white/5"
      hitSlop={6}
    >
      <Animated.View style={{ opacity: fadeAnim }}>
        <AppIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={12}
          color={copied ? COLORS.success : COLORS.muted}
        />
      </Animated.View>
      <Text
        className="text-[10px] font-medium"
        style={{ color: copied ? COLORS.success : COLORS.muted }}
      >
        {copied ? "Copied" : "Copy"}
      </Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// CollapsibleSection — single accordion item inside the card
// ---------------------------------------------------------------------------

interface CollapsibleSectionProps {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({
  label,
  defaultOpen = false,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const chevronAnim = useRef(new Animated.Value(defaultOpen ? 1 : 0)).current;

  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      Animated.timing(chevronAnim, {
        toValue: next ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }).start();
      return next;
    });
  }, [chevronAnim]);

  const chevronRotate = chevronAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "-180deg"],
  });

  return (
    <ToolCardInner dense>
      <Pressable
        onPress={toggle}
        className="flex-row items-center justify-between"
      >
        <SectionLabel>{label}</SectionLabel>
        <Animated.View
          style={{ transform: [{ rotate: chevronRotate }], marginBottom: 6 }}
        >
          <AppIcon icon={ArrowDown02Icon} size={14} color="#a1a1aa" />
        </Animated.View>
      </Pressable>
      {open && <View className="mt-1">{children}</View>}
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// OutputBlock — single colored block inside the output section
// ---------------------------------------------------------------------------

interface OutputBlockProps {
  label?: string;
  text: string;
  color: string;
}

function OutputBlock({ label, text, color }: OutputBlockProps) {
  return (
    <View>
      {label && (
        <Text className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">
          {label}
        </Text>
      )}
      <View
        style={{
          backgroundColor: COLORS.outputBg,
          borderRadius: 10,
          padding: 10,
        }}
      >
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingRight: 4 }}
        >
          <RNText
            style={{
              fontFamily: MONO_FONT,
              fontSize: 12,
              lineHeight: 18,
              color,
            }}
          >
            {text}
          </RNText>
        </ScrollView>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// OutputSection — full output panel (mirrors web CodeExecutionOutput body)
// ---------------------------------------------------------------------------

interface OutputSectionProps {
  output: CodeOutput;
  status?: CodeData["status"];
  language?: string;
}

function OutputSection({ output, status, language }: OutputSectionProps) {
  const hasStdout = !!output.stdout;
  const hasStderr = !!output.stderr;
  const hasResults = !!(output.results && output.results.length > 0);
  const hasError = !!output.error;

  const copyText = [
    output.stdout,
    output.stderr,
    ...(output.results ?? []),
    output.error,
  ]
    .filter(Boolean)
    .join("\n");

  // Header status (icon + label) mirrors the web header above the output body
  const headerStatus = (() => {
    if (status === "executing") {
      return { label: "Running", color: COLORS.accent };
    }
    if (status === "error" || hasError) {
      return { label: "Failed", color: COLORS.failed };
    }
    if (status === "completed" && !hasError) {
      return { label: "Success", color: COLORS.success };
    }
    return { label: "Output", color: "#a1a1aa" };
  })();

  if (!hasStdout && !hasStderr && !hasResults && !hasError) {
    if (status === "executing") {
      return (
        <View className="flex-row items-center gap-2 py-2">
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: COLORS.accent,
            }}
          />
          <Text className="text-zinc-400 text-xs">
            Executing {language ?? "code"}…
          </Text>
        </View>
      );
    }
    return (
      <Text className="text-zinc-500 text-xs text-center py-2">
        No output produced
      </Text>
    );
  }

  return (
    <View className="gap-2">
      {/* Output header — status text + copy button */}
      <View className="flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <View
            style={{
              width: 6,
              height: 6,
              borderRadius: 3,
              backgroundColor: headerStatus.color,
            }}
          />
          <Text
            className="text-xs font-medium"
            style={{ color: headerStatus.color }}
          >
            {headerStatus.label}
          </Text>
        </View>
        {copyText.length > 0 && <CopyButton text={copyText} />}
      </View>

      {hasStdout && (
        <OutputBlock
          label="stdout"
          text={output.stdout ?? ""}
          color={COLORS.stdoutText}
        />
      )}

      {hasResults && (
        <OutputBlock
          label="results"
          text={(output.results ?? []).join("\n")}
          color={COLORS.resultsText}
        />
      )}

      {hasStderr && (
        <OutputBlock
          label="stderr"
          text={output.stderr ?? ""}
          color={COLORS.errorText}
        />
      )}

      {hasError && (
        <OutputBlock
          label="execution error"
          text={output.error ?? ""}
          color={COLORS.errorText}
        />
      )}

      {/* Status footer — mirrors web CodeExecutionOutput footer row */}
      <View className="flex-row items-center justify-between pt-1">
        <Text className="text-xs text-zinc-500">
          Status: {status ?? "unknown"}
        </Text>
        {!hasError && !hasStderr ? (
          <Text className="text-xs text-green-400">Success</Text>
        ) : (
          <Text className="text-xs text-red-400">Failed</Text>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Chart adapter — CodeChartData → ChartDisplayData (chart-card input)
// ---------------------------------------------------------------------------

function toChartDisplayData(chart: CodeChartData): ChartDisplayData {
  return {
    id: chart.id,
    url: chart.url,
    text: chart.text,
    type: chart.type,
    title: chart.title,
    description: chart.description,
    chart_data: chart.chart_data,
  };
}

// ---------------------------------------------------------------------------
// CodeExecutionCard — main export (mirrors web CodeExecutionSection)
// ---------------------------------------------------------------------------

export function CodeExecutionCard({ data }: { data: CodeData }) {
  const language = data.language || "text";
  const hasError = !!(data.error || data.output?.error || data.output?.stderr);
  const hasCode = !!data.code;
  const hasOutput = !!(
    data.output &&
    (data.output.stdout ||
      data.output.stderr ||
      data.output.results?.length ||
      data.output.error)
  );

  const charts = (data.charts ?? [])
    .filter((c) => c?.chart_data || c?.url)
    .map(toChartDisplayData);
  const hasChart = charts.length > 0;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={SourceCodeCircleIcon}
        title="Code Execution"
        subtitle={language !== "text" ? language : undefined}
        trailing={<StatusChip status={data.status} hasError={hasError} />}
      />

      <View className="gap-2">
        {/* Executed Code section */}
        {hasCode && (
          <CollapsibleSection label="Executed Code" defaultOpen={!hasOutput}>
            <CodeBlock code={data.code ?? ""} language={language} />
          </CollapsibleSection>
        )}

        {/* Output section — open by default to mirror web defaultExpandedKeys */}
        {(hasOutput || data.status === "executing") && (
          <CollapsibleSection label="Output" defaultOpen>
            {data.output ? (
              <OutputSection
                output={data.output}
                status={data.status}
                language={language}
              />
            ) : (
              <View className="flex-row items-center gap-2 py-2">
                <View
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: COLORS.accent,
                  }}
                />
                <Text className="text-zinc-400 text-xs">
                  Executing {language} code…
                </Text>
              </View>
            )}
          </CollapsibleSection>
        )}

        {/* Ready-to-execute placeholder — no code, no output, not running */}
        {!hasCode && !hasOutput && data.status !== "executing" && (
          <ToolCardInner dense>
            <Text className="text-zinc-500 text-xs text-center py-2">
              Ready to execute
            </Text>
          </ToolCardInner>
        )}

        {/* Charts section — defaultOpen, mirrors web Accordion charts key */}
        {hasChart && (
          <CollapsibleSection label="Charts" defaultOpen>
            <View className="gap-2">
              {charts.map((item, idx) => (
                <ChartItem key={item.id ?? `chart-${idx}`} item={item} />
              ))}
            </View>
          </CollapsibleSection>
        )}

        {/* Top-level error fallback — only when there's no output container */}
        {data.error && !data.output && (
          <ToolCardInner dense>
            <SectionLabel>Error</SectionLabel>
            <RNText
              style={{
                fontFamily: MONO_FONT,
                fontSize: 12,
                lineHeight: 18,
                color: COLORS.errorText,
              }}
            >
              {data.error}
            </RNText>
          </ToolCardInner>
        )}
      </View>
    </ToolCardShell>
  );
}
