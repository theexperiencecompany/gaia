import { Card } from "heroui-native";
import type React from "react";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import {
  Cancel01Icon,
  CheckmarkCircle02Icon,
  CodeIcon,
  SourceCodeCircleIcon,
} from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import { THEME } from "@/features/chat/components/code-block/syntax-theme";
import { tokenizeLine } from "@/features/chat/components/code-block/tokenizer";

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

// ─── Syntax-highlighted code renderer ────────────────────────────────────────

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
      style={{ backgroundColor: THEME.background }}
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

// ─── Status helpers ───────────────────────────────────────────────────────────

function StatusIcon({
  status,
  hasError,
}: {
  status?: CodeData["status"];
  hasError: boolean;
}) {
  if (status === "executing") {
    return (
      <View className="w-3 h-3 rounded-full border-2 border-[#00bbff] border-t-transparent" />
    );
  }
  if (status === "error" || hasError) {
    return <AppIcon icon={Cancel01Icon} size={13} color="#ff453a" />;
  }
  if (status === "completed" && !hasError) {
    return <AppIcon icon={CheckmarkCircle02Icon} size={13} color="#34c759" />;
  }
  return <AppIcon icon={SourceCodeCircleIcon} size={13} color="#8e8e93" />;
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

// ─── Collapsible section ──────────────────────────────────────────────────────

function CollapsibleSection({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ReactElement;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <View className="rounded-xl overflow-hidden border border-white/8 mb-2">
      <Pressable
        onPress={() => setOpen((prev) => !prev)}
        className="flex-row items-center justify-between px-3 py-2.5 bg-white/5 active:opacity-70"
      >
        <View className="flex-row items-center gap-2">
          {icon}
          <Text className="text-sm font-medium text-foreground">{title}</Text>
        </View>
        <Text className="text-muted text-xs">{open ? "▲" : "▼"}</Text>
      </Pressable>
      {open && <View>{children}</View>}
    </View>
  );
}

// ─── Output display ───────────────────────────────────────────────────────────

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
      <View className="flex-row items-center gap-3 p-3">
        <View className="w-2 h-2 rounded-full bg-[#00bbff]" />
        <Text className="text-sm text-muted">Executing {language} code…</Text>
      </View>
    );
  }

  if (!output) {
    return (
      <View className="p-3">
        <Text className="text-sm text-muted text-center">Ready to execute</Text>
      </View>
    );
  }

  return (
    <View style={{ backgroundColor: "#0d0d0d" }}>
      {/* stdout */}
      {!!output.stdout && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ padding: 12 }}
        >
          <Text
            style={{
              color: "#34c759",
              fontFamily: "monospace",
              fontSize: 12,
              lineHeight: 18,
            }}
          >
            {output.stdout}
          </Text>
        </ScrollView>
      )}

      {/* results */}
      {output.results && output.results.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{
            padding: 12,
            paddingTop: output.stdout ? 0 : 12,
          }}
        >
          <View>
            {output.results.map((result, idx) => {
              const resultKey = `result-${idx}`;
              return (
                <Text
                  key={resultKey}
                  style={{
                    color: "#00bbff",
                    fontFamily: "monospace",
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
      )}

      {/* stderr */}
      {!!output.stderr && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ padding: 12, paddingTop: 0 }}
        >
          <Text
            style={{
              color: "#ff453a",
              fontFamily: "monospace",
              fontSize: 12,
              lineHeight: 18,
            }}
          >
            {output.stderr}
          </Text>
        </ScrollView>
      )}

      {/* execution error */}
      {!!output.error && (
        <View style={{ padding: 12, paddingTop: 0 }}>
          <Text
            className="text-[10px] font-semibold text-muted mb-1"
            style={{ letterSpacing: 0.5 }}
          >
            EXECUTION ERROR
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Text
              style={{
                color: "#ff453a",
                fontFamily: "monospace",
                fontSize: 12,
                lineHeight: 18,
              }}
            >
              {output.error}
            </Text>
          </ScrollView>
        </View>
      )}

      {/* footer status */}
      <View className="flex-row items-center justify-between px-3 py-2 border-t border-white/8">
        <Text className="text-[10px] text-muted">
          Status: {status ?? "unknown"}
        </Text>
        <Text
          className={`text-[10px] font-medium ${hasError ? "text-red-400" : "text-[#34c759]"}`}
        >
          {hasError ? "Failed" : "Success"}
        </Text>
      </View>

      {/* no output */}
      {!output.stdout &&
        !output.stderr &&
        !output.results?.length &&
        !output.error && (
          <View className="py-4 px-3">
            <Text className="text-sm text-muted text-center">
              No output produced
            </Text>
          </View>
        )}
    </View>
  );
}

// ─── Main card ────────────────────────────────────────────────────────────────

export function CodeExecutionCard({ data }: { data: CodeData }) {
  const language = data.language || "text";
  const hasError = !!(data.error || data.output?.error || data.output?.stderr);
  const _hasOutput = !!(
    data.output?.stdout ||
    data.output?.stderr ||
    data.output?.results?.length ||
    data.output?.error
  );

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={SourceCodeCircleIcon} size={14} color="#8e8e93" />
          <Text className="text-xs text-muted flex-1">Code Execution</Text>
          {!!language && language !== "text" && (
            <View className="rounded-full bg-white/10 px-2 py-0.5">
              <Text className="text-[10px] text-muted font-medium">
                {language}
              </Text>
            </View>
          )}
        </View>

        {/* Code section */}
        {!!data.code && (
          <CollapsibleSection
            title="Executed Code"
            defaultOpen={false}
            icon={<AppIcon icon={CodeIcon} size={13} color="#8e8e93" />}
          >
            <SyntaxHighlightedCode code={data.code} language={language} />
          </CollapsibleSection>
        )}

        {/* Output section */}
        <CollapsibleSection
          title={getStatusText(data.status, hasError)}
          defaultOpen
          icon={<StatusIcon status={data.status} hasError={hasError} />}
        >
          <OutputContent
            output={data.output}
            status={data.status}
            language={language}
          />
        </CollapsibleSection>

        {/* Inline error (when output object is absent) */}
        {data.error && !data.output && (
          <View className="rounded-xl bg-red-500/10 border border-red-500/20 p-3 mt-1">
            <Text
              className="text-[10px] font-semibold text-red-400 mb-1"
              style={{ letterSpacing: 0.5 }}
            >
              ERROR
            </Text>
            <Text
              className="text-sm text-red-400"
              style={{ fontFamily: "monospace" }}
            >
              {data.error}
            </Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
