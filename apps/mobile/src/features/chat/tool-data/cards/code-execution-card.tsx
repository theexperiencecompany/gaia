import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  SourceCodeCircleIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { THEME } from "../../components/code-block/syntax-theme";
import { tokenizeLine } from "../../components/code-block/tokenizer";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "../primitives";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CodeOutput {
  stdout?: string;
  stderr?: string;
  results?: string[];
  error?: string | null;
}

export interface CodeData {
  language?: string;
  code?: string;
  output?: CodeOutput | null;
  status?: "executing" | "completed" | "error";
  error?: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MONO_FONT = "RobotoMono_400Regular";

const STDOUT_GREEN = "#86efac";
const STDERR_RED = "#fca5a5";
const RESULT_BLUE = "#60a5fa";

// ─── Syntax-highlighted code ─────────────────────────────────────────────────

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
            style={{ color, fontFamily: MONO_FONT, fontSize: 12 }}
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
                fontFamily: MONO_FONT,
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

// ─── Status helpers ──────────────────────────────────────────────────────────

function StatusIcon({
  status,
  hasError,
}: {
  status?: CodeData["status"];
  hasError: boolean;
}) {
  if (status === "executing") {
    return (
      <View className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent" />
    );
  }
  if (status === "error" || hasError) {
    return <AppIcon icon={Cancel01Icon} size={12} color="#f87171" />;
  }
  if (status === "completed" && !hasError) {
    return <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#4ade80" />;
  }
  return <AppIcon icon={SourceCodeCircleIcon} size={12} color="#a1a1aa" />;
}

function getStatusText(
  status?: CodeData["status"],
  hasError?: boolean,
): string {
  if (status === "executing") return "Running";
  if (status === "error" || hasError) return "Failed";
  if (status === "completed" && !hasError) return "Success";
  return "Output";
}

function statusPillClasses(
  status?: CodeData["status"],
  hasError?: boolean,
): string {
  if (status === "executing") return "bg-zinc-700";
  if (status === "error" || hasError) return "bg-red-500/15";
  if (status === "completed" && !hasError) return "bg-green-500/15";
  return "bg-zinc-700";
}

function statusPillTextClasses(
  status?: CodeData["status"],
  hasError?: boolean,
): string {
  if (status === "executing") return "text-zinc-200";
  if (status === "error" || hasError) return "text-red-400";
  if (status === "completed" && !hasError) return "text-green-400";
  return "text-zinc-200";
}

// ─── Copy button ─────────────────────────────────────────────────────────────

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

// ─── Collapsible section ─────────────────────────────────────────────────────

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <View className="mb-2">
      <Pressable
        onPress={() => setOpen((prev) => !prev)}
        className="flex-row items-center justify-between py-2 active:opacity-70"
      >
        <Text className="text-sm font-medium text-zinc-300">{title}</Text>
        <Text className="text-zinc-500 text-xs">{open ? "Hide" : "Show"}</Text>
      </Pressable>
      {open && <View>{children}</View>}
    </View>
  );
}

// ─── Output content ──────────────────────────────────────────────────────────

function OutputContent({
  output,
  status,
  language,
}: {
  output?: CodeOutput | null;
  status?: CodeData["status"];
  language: string;
}) {
  const hasError = !!(output?.error || output?.stderr);

  if (status === "executing" && !output) {
    return (
      <View className="flex-row items-center gap-3 py-4">
        <View className="w-2 h-2 rounded-full bg-blue-400" />
        <Text className="text-sm text-zinc-400">
          Executing {language} code…
        </Text>
      </View>
    );
  }

  if (!output) {
    return (
      <View className="py-4">
        <Text className="text-sm text-zinc-500 text-center">
          Ready to execute
        </Text>
      </View>
    );
  }

  const hasAnyContent =
    !!output.stdout ||
    !!output.stderr ||
    (output.results && output.results.length > 0) ||
    !!output.error;

  return (
    <View className="gap-2">
      {/* stdout */}
      {!!output.stdout && (
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
                color: STDOUT_GREEN,
                fontFamily: MONO_FONT,
                fontSize: 12,
                lineHeight: 18,
              }}
            >
              {output.stdout}
            </Text>
          </ScrollView>
        </View>
      )}

      {/* results */}
      {output.results && output.results.length > 0 && (
        <View
          className="rounded-xl overflow-hidden"
          style={{ backgroundColor: "#000" }}
        >
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ padding: 12 }}
          >
            <View>
              {output.results.map((result, idx) => {
                const resultKey = `result-${idx}`;
                return (
                  <Text
                    key={resultKey}
                    style={{
                      color: RESULT_BLUE,
                      fontFamily: MONO_FONT,
                      fontSize: 12,
                      lineHeight: 18,
                    }}
                  >
                    {result}
                  </Text>
                );
              })}
            </View>
          </ScrollView>
        </View>
      )}

      {/* stderr */}
      {!!output.stderr && (
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
                color: STDERR_RED,
                fontFamily: MONO_FONT,
                fontSize: 12,
                lineHeight: 18,
              }}
            >
              {output.stderr}
            </Text>
          </ScrollView>
        </View>
      )}

      {/* execution error */}
      {!!output.error && (
        <View>
          <Text
            className="text-[10px] font-semibold text-zinc-500 mb-1"
            style={{ letterSpacing: 0.5 }}
          >
            EXECUTION ERROR
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
                  color: STDERR_RED,
                  fontFamily: MONO_FONT,
                  fontSize: 12,
                  lineHeight: 18,
                }}
              >
                {output.error}
              </Text>
            </ScrollView>
          </View>
        </View>
      )}

      {/* status footer */}
      <View className="flex-row items-center justify-between pt-1">
        <Text className="text-[11px] text-zinc-500">
          Status: {status ?? "unknown"}
        </Text>
        <Text
          className={`text-[11px] font-medium ${hasError ? "text-red-400" : "text-green-400"}`}
        >
          {hasError ? "Failed" : "Success"}
        </Text>
      </View>

      {!hasAnyContent && (
        <Text className="text-sm text-zinc-500 text-center py-2">
          No output produced
        </Text>
      )}
    </View>
  );
}

// ─── Main card ───────────────────────────────────────────────────────────────

export function CodeExecutionCard({ data }: { data: CodeData }) {
  const language = data.language || "text";
  const hasError = !!(data.error || data.output?.error || data.output?.stderr);
  const hasAnyOutput =
    !!data.output?.stdout ||
    !!data.output?.stderr ||
    (data.output?.results && data.output.results.length > 0) ||
    !!data.output?.error;

  const copyText = [
    data.output?.stdout,
    data.output?.stderr,
    ...(data.output?.results ?? []),
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={SourceCodeCircleIcon}
        iconColor="#a1a1aa"
        title="Code Execution"
        trailing={
          <View
            className={`flex-row items-center gap-1.5 rounded-full px-2 py-1 ${statusPillClasses(data.status, hasError)}`}
          >
            <StatusIcon status={data.status} hasError={hasError} />
            <Text
              className={`text-[11px] font-medium ${statusPillTextClasses(data.status, hasError)}`}
            >
              {getStatusText(data.status, hasError)}
            </Text>
          </View>
        }
      />

      {/* Code section */}
      {!!data.code && (
        <ToolCardInner className="mb-2">
          <CollapsibleSection title="Executed Code" defaultOpen={false}>
            <SyntaxHighlightedCode code={data.code} language={language} />
          </CollapsibleSection>
        </ToolCardInner>
      )}

      {/* Output section */}
      <ToolCardInner>
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-sm font-medium text-zinc-300">
            {getStatusText(data.status, hasError)}
          </Text>
          {hasAnyOutput && copyText.length > 0 && (
            <CopyButton text={copyText} />
          )}
        </View>
        <OutputContent
          output={data.output}
          status={data.status}
          language={language}
        />
      </ToolCardInner>

      {/* Inline error when output object is absent */}
      {data.error && !data.output && (
        <ToolCardInner className="mt-2">
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
                  color: STDERR_RED,
                  fontFamily: MONO_FONT,
                  fontSize: 12,
                  lineHeight: 18,
                }}
              >
                {data.error}
              </Text>
            </ScrollView>
          </View>
        </ToolCardInner>
      )}
    </ToolCardShell>
  );
}
