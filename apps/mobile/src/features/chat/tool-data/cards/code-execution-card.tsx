import type { CodeChartData, CodeData, CodeOutput } from "@gaia/shared";
import { useCallback, useRef, useState } from "react";
import { Animated, Pressable, ScrollView, View } from "react-native";
import {
  ArrowDown02Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  SourceCodeCircleIcon,
} from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { THEME } from "@/features/chat/components/code-block/syntax-theme";
import { tokenizeLine } from "@/features/chat/components/code-block/tokenizer";
import {
  ChartCard,
  type ChartData,
} from "@/features/chat/components/tool-cards/chart-card";
import {
  SectionLabel,
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Syntax-highlighted code renderer ----------------------------------------

function SyntaxLine({ line, language }: { line: string; language: string }) {
  const tokens = tokenizeLine(line, language);
  return (
    <Text>
      {tokens.map((token, idx) => {
        const color =
          token.type === "plain"
            ? THEME.plain
            : ((THEME[token.type as keyof typeof THEME] as
                | string
                | undefined) ?? THEME.plain);
        return (
          <Text
            // biome-ignore lint/suspicious/noArrayIndexKey: stable token list per line
            key={idx}
            style={{ color, fontFamily: "monospace" }}
          >
            {token.value}
          </Text>
        );
      })}
    </Text>
  );
}

function SyntaxHighlightedCode({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const lines = code.split("\n");
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={{ backgroundColor: THEME.background, borderRadius: 12 }}
      contentContainerStyle={{ padding: 12 }}
    >
      <View>
        {lines.map((line, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable line list
          <View key={idx} className="flex-row">
            <Text
              style={{
                color: THEME.gutterText,
                fontFamily: "monospace",
                fontSize: 11,
                minWidth: 28,
                marginRight: 8,
                textAlign: "right",
              }}
            >
              {idx + 1}
            </Text>
            <SyntaxLine line={line} language={language} />
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// -- Status chip --------------------------------------------------------------

function StatusChip({
  status,
  hasError,
}: {
  status?: CodeData["status"];
  hasError: boolean;
}) {
  if (status === "executing") {
    return (
      <View className="flex-row items-center gap-1.5 px-2 py-1 rounded-full bg-zinc-700">
        <View className="w-1.5 h-1.5 rounded-full bg-[#00bbff]" />
        <Text className="text-[10px] font-semibold uppercase text-zinc-300">
          Running
        </Text>
      </View>
    );
  }
  if (status === "error" || hasError) {
    return (
      <View className="flex-row items-center gap-1 px-2 py-1 rounded-full bg-red-500/15">
        <AppIcon icon={Cancel01Icon} size={11} color="#ff453a" />
        <Text className="text-[10px] font-semibold uppercase text-red-400">
          Failed
        </Text>
      </View>
    );
  }
  if (status === "completed" && !hasError) {
    return (
      <View className="flex-row items-center gap-1 px-2 py-1 rounded-full bg-green-500/15">
        <AppIcon icon={CheckmarkCircle02Icon} size={11} color="#34c759" />
        <Text className="text-[10px] font-semibold uppercase text-green-400">
          Success
        </Text>
      </View>
    );
  }
  return null;
}

// -- Collapsible section ------------------------------------------------------

function CollapsibleSection({
  label,
  defaultOpen = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
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

// -- Output display -----------------------------------------------------------

function OutputSection({ output }: { output: CodeOutput }) {
  const hasStdout = !!output.stdout;
  const hasStderr = !!output.stderr;
  const hasResults = !!(output.results && output.results.length > 0);
  const hasError = !!output.error;

  if (!hasStdout && !hasStderr && !hasResults && !hasError) {
    return <Text className="text-zinc-500 text-xs">No output produced</Text>;
  }

  return (
    <View className="gap-2">
      {hasStdout && (
        <View>
          <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            stdout
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingRight: 8 }}
          >
            <Text
              className="text-zinc-100 text-xs"
              style={{ fontFamily: "monospace", lineHeight: 18 }}
            >
              {output.stdout}
            </Text>
          </ScrollView>
        </View>
      )}

      {hasResults && (
        <View>
          <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            results
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingRight: 8 }}
          >
            <View>
              {output.results?.map((result, idx) => (
                <Text
                  // biome-ignore lint/suspicious/noArrayIndexKey: results list order is stable
                  key={`result-${idx}`}
                  className="text-zinc-300 text-xs"
                  style={{ fontFamily: "monospace", lineHeight: 18 }}
                >
                  {result}
                </Text>
              ))}
            </View>
          </ScrollView>
        </View>
      )}

      {hasStderr && (
        <View>
          <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            stderr
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingRight: 8 }}
          >
            <Text
              className="text-red-400 text-xs"
              style={{ fontFamily: "monospace", lineHeight: 18 }}
            >
              {output.stderr}
            </Text>
          </ScrollView>
        </View>
      )}

      {hasError && (
        <View>
          <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
            error
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Text
              className="text-red-400 text-xs"
              style={{ fontFamily: "monospace", lineHeight: 18 }}
            >
              {output.error}
            </Text>
          </ScrollView>
        </View>
      )}
    </View>
  );
}

// -- Chart adapter ------------------------------------------------------------

function normalizeChartType(type?: string): ChartData["type"] {
  if (type === "line") return "line";
  if (type === "pie") return "pie";
  return "bar";
}

function toChartData(chart: CodeChartData): ChartData | null {
  const source = chart.chart_data;
  if (!source || !source.elements || source.elements.length === 0) {
    return null;
  }
  return {
    type: normalizeChartType(source.type),
    title: source.title || chart.title,
    data: source.elements.map((el) => ({
      label: el.label,
      value: el.value,
    })),
    xLabel: source.x_label,
    yLabel: source.y_label,
  };
}

// -- Main card ----------------------------------------------------------------

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
    .map(toChartData)
    .filter((c): c is ChartData => c !== null);
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
        {hasCode && (
          <CollapsibleSection label="Code" defaultOpen={!hasOutput}>
            <SyntaxHighlightedCode code={data.code ?? ""} language={language} />
          </CollapsibleSection>
        )}

        {(hasOutput || data.status === "executing") && (
          <CollapsibleSection label="Output" defaultOpen>
            {data.output ? (
              <OutputSection output={data.output} />
            ) : (
              <View className="flex-row items-center gap-2">
                <View className="w-1.5 h-1.5 rounded-full bg-[#00bbff]" />
                <Text className="text-zinc-400 text-xs">
                  Executing {language} code…
                </Text>
              </View>
            )}
          </CollapsibleSection>
        )}

        {hasChart &&
          charts.map((chart, idx) => (
            <CollapsibleSection
              // biome-ignore lint/suspicious/noArrayIndexKey: stable chart list per run
              key={`chart-${idx}`}
              label={charts.length > 1 ? `Chart ${idx + 1}` : "Chart"}
              defaultOpen
            >
              <ChartCard toolData={chart} />
            </CollapsibleSection>
          ))}

        {data.error && !data.output && (
          <ToolCardInner dense>
            <Text className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">
              Error
            </Text>
            <Text
              className="text-red-400 text-sm"
              style={{ fontFamily: "monospace" }}
            >
              {data.error}
            </Text>
          </ToolCardInner>
        )}
      </View>
    </ToolCardShell>
  );
}
