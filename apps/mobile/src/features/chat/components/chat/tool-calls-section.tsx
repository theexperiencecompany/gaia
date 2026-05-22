import { normalizeCategoryName } from "@gaia/shared/icons";
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, ArrowDown01Icon, ToolsIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "../../utils/tool-icons";

export interface ToolCallEntry {
  tool_call_id?: string;
  tool_name?: string;
  tool_category?: string;
  message?: string;
  inputs?: Record<string, unknown>;
  output?: string;
  integration_name?: string;
  icon_url?: string;
  show_category?: boolean;
  status?: "running" | "done" | "error";
}

interface ToolCallsSectionProps {
  tool_calls_data: ToolCallEntry[];
}

function formatToolName(toolName: string): string {
  return toolName
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\s+tool$/i, "")
    .trim();
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function looksLikeJson(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

/**
 * Mirrors apps/web/src/utils/jsonFormatters.ts → formatJsonLikeString.
 * Pretty-prints structured input objects/strings exactly like the web
 * tool-call accordion does, even when JSON is incomplete or truncated.
 */
function formatJsonLikeString(str: string): string {
  const parsed = safeJsonParse(str);
  if (parsed !== null) {
    return JSON.stringify(parsed, null, 2);
  }
  let result = "";
  let indentLevel = 0;
  let inString = false;
  let escaped = false;
  const indent = "  ";
  for (let i = 0; i < str.length; i++) {
    const char = str[i];
    if (escaped) {
      result += char;
      escaped = false;
      continue;
    }
    if (char === "\\" && inString) {
      result += char;
      escaped = true;
      continue;
    }
    if (char === '"' && !escaped) {
      inString = !inString;
      result += char;
      continue;
    }
    if (inString) {
      result += char;
      continue;
    }
    switch (char) {
      case "{":
      case "[":
        result += char;
        indentLevel++;
        result += `\n${indent.repeat(indentLevel)}`;
        break;
      case "}":
      case "]":
        indentLevel = Math.max(0, indentLevel - 1);
        result += `\n${indent.repeat(indentLevel)}${char}`;
        break;
      case ",":
        result += `${char}\n${indent.repeat(indentLevel)}`;
        break;
      case ":":
        result += ": ";
        break;
      case " ":
      case "\n":
      case "\r":
      case "\t":
        break;
      default:
        result += char;
    }
  }
  return result;
}

interface NormalizedValue {
  data: unknown;
  isStructured: boolean;
}

function normalizeValue(value: unknown): NormalizedValue {
  if (value == null) return { data: "", isStructured: false };
  if (Array.isArray(value)) {
    return { data: value, isStructured: true };
  }
  if (isPlainObject(value)) {
    return { data: value, isStructured: true };
  }
  if (typeof value === "string") {
    const parsed = safeJsonParse(value);
    if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
      return { data: parsed, isStructured: true };
    }
    if (looksLikeJson(value)) {
      return { data: value, isStructured: true };
    }
    return { data: value, isStructured: false };
  }
  return { data: String(value), isStructured: false };
}

function renderInputText(content: unknown): string {
  const { data, isStructured } = normalizeValue(content);
  if (isStructured) {
    return typeof data === "string"
      ? formatJsonLikeString(data)
      : JSON.stringify(data, null, 2);
  }
  return String(data);
}

function ToolIcon({
  category,
  iconUrl,
  size = 21,
}: {
  category: string;
  iconUrl?: string;
  size?: number;
}) {
  const icon = getToolCategoryIcon(
    category,
    { size, showBackground: false },
    iconUrl,
  );
  if (icon) return icon;
  return (
    <View
      style={{
        width: size + 8,
        height: size + 8,
        borderRadius: 8,
        backgroundColor: "rgba(63,63,70,0.6)",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <AppIcon icon={ToolsIcon} size={size - 4} color="#a1a1aa" />
    </View>
  );
}

// Web: SHOWICONS = 10 in ToolCallsSection.tsx
const MAX_STACKED_ICONS = 10;

function StackedToolIcons({ calls }: { calls: ToolCallEntry[] }) {
  const seenCategories = new Set<string>();
  const uniqueIcons = calls.filter((call) => {
    const category = normalizeCategoryName(call.tool_category || "general");
    if (seenCategories.has(category)) return false;
    seenCategories.add(category);
    return true;
  });

  const displayIcons = uniqueIcons.slice(0, MAX_STACKED_ICONS);
  const overflow = uniqueIcons.length - MAX_STACKED_ICONS;

  // Web: only render the row when there are 2+ unique icons.
  if (displayIcons.length <= 1) return null;

  return (
    // Web: flex min-h-8 items-center -space-x-2 (8px overlap, 32px row height)
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        minHeight: 32,
        marginRight: 0,
      }}
    >
      {displayIcons.map((call, index) => (
        // Web wrapper: relative flex min-w-8 items-center justify-center (32px col)
        <View
          key={`${call.tool_name || "tool"}-${index}`}
          style={{
            minWidth: 32,
            height: 32,
            alignItems: "center",
            justifyContent: "center",
            marginLeft: index === 0 ? 0 : -8,
            zIndex: index,
            transform: [{ rotate: index % 2 === 0 ? "8deg" : "-8deg" }],
          }}
        >
          <ToolIcon
            category={call.tool_category || "general"}
            iconUrl={call.icon_url}
            size={21}
          />
        </View>
      ))}
      {overflow > 0 && (
        // Web: size-7 min-h-7 min-w-7 rounded-lg bg-zinc-700/60 text-xs text-foreground-500
        <View
          style={{
            marginLeft: -8,
            zIndex: 0,
            width: 28,
            height: 28,
            minHeight: 28,
            minWidth: 28,
            borderRadius: 8,
            backgroundColor: "rgba(63,63,70,0.6)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text
            style={{
              fontSize: 12,
              color: "#a1a1aa",
              fontWeight: "400",
            }}
          >
            +{overflow}
          </Text>
        </View>
      )}
    </View>
  );
}

function ToolCallItem({
  call,
  isLast,
  isExpanded,
  onToggle,
}: {
  call: ToolCallEntry;
  isLast: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const hasInputs =
    call.inputs &&
    typeof call.inputs === "object" &&
    Object.keys(call.inputs).length > 0;
  const hasOutput = !!(call.output && call.output.length > 0);
  const hasDetails = !!hasInputs || hasOutput;

  const displayName = call.message || formatToolName(call.tool_name || "Tool");

  const rotation = useSharedValue(isExpanded ? 0 : -90);
  useEffect(() => {
    rotation.value = withTiming(isExpanded ? 0 : -90, { duration: 200 });
  }, [isExpanded, rotation]);
  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  // Single-line header — name + chevron, vertically centered to the 32px icon.
  // Mobile intentionally drops web's category subtitle ("Search", etc.) — the
  // narrow column makes the two-line stack feel cluttered.
  const headerRow = (
    <View
      style={{
        minHeight: 32,
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
      }}
    >
      <Text
        style={{
          fontSize: 12,
          color: "#a1a1aa",
          fontWeight: "500",
          flexShrink: 1,
        }}
        numberOfLines={1}
      >
        {displayName}
      </Text>
      {hasDetails && (
        <Animated.View style={chevronStyle}>
          <AppIcon icon={ArrowDown01Icon} size={14} color="#71717a" />
        </Animated.View>
      )}
    </View>
  );

  const content = (
    <View style={{ flex: 1, minWidth: 0 }}>
      {headerRow}
      {hasDetails && isExpanded && (
        // Web detail outer:
        //   mt-2 space-y-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 mb-3 w-fit
        //   space-y-2 = 8px gap between Input/Output blocks
        // Mobile: stretch full column width (was alignSelf: flex-start which
        // collapsed the panel to its content) so the Input/Output text has
        // breathing room on a phone screen. Web's max-w-140 (560px) cap is
        // applied at the parent ToolCallsSection wrapper.
        <View
          style={{
            marginTop: 8,
            marginBottom: 12,
            backgroundColor: "rgba(39,39,42,0.5)",
            borderRadius: 12,
            padding: 12,
            gap: 8,
            alignSelf: "stretch",
          }}
        >
          {hasInputs && (
            <View>
              {/* Web: span text-zinc-500 font-medium mb-1 (inherits text-[11px]) */}
              <Text
                style={{
                  fontSize: 11,
                  color: "#71717a",
                  fontWeight: "500",
                  marginBottom: 4,
                }}
              >
                Input
              </Text>
              {/* Web inner pre:
                   bg-zinc-900/50 rounded-xl p-3 max-h-60 overflow-y-auto
                   text-xs text-zinc-400 whitespace-pre-wrap */}
              <View
                style={{
                  backgroundColor: "rgba(24,24,27,0.5)",
                  borderRadius: 12,
                  padding: 12,
                  maxHeight: 240,
                }}
              >
                <Text
                  style={{
                    fontFamily: "AnonymousPro_400Regular",
                    fontSize: 12,
                    lineHeight: 18,
                    color: "#a1a1aa",
                  }}
                >
                  {renderInputText(call.inputs)}
                </Text>
              </View>
            </View>
          )}
          {hasOutput && (
            <View>
              {/* Web: span text-zinc-500 font-medium mb-1 (inherits text-[11px]) */}
              <Text
                style={{
                  fontSize: 11,
                  color: "#71717a",
                  fontWeight: "500",
                  marginBottom: 4,
                }}
              >
                Output
              </Text>
              {/* Web inner pre:
                   bg-zinc-900/50 rounded-xl p-3 max-h-60 overflow-y-auto
                   text-xs text-zinc-400 whitespace-pre-wrap */}
              <View
                style={{
                  backgroundColor: "rgba(24,24,27,0.5)",
                  borderRadius: 12,
                  padding: 12,
                  maxHeight: 240,
                }}
              >
                <Text
                  style={{
                    fontFamily: "AnonymousPro_400Regular",
                    fontSize: 12,
                    lineHeight: 18,
                    color: "#a1a1aa",
                  }}
                >
                  {renderInputText(call.output)}
                </Text>
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );

  // Web icon column:
  //   <div className="flex flex-col items-center self-stretch">
  //     <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
  //       21px icon
  //     {connector w-px flex-1 bg-default-200 min-h-4}
  const iconColumn = (
    <View style={{ alignItems: "center", alignSelf: "stretch" }}>
      <View
        style={{
          width: 32,
          height: 32,
          minWidth: 32,
          minHeight: 32,
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <ToolIcon
          category={call.tool_category || "general"}
          iconUrl={call.icon_url}
          size={21}
        />
      </View>
      {!isLast && (
        // Web: w-px flex-1 bg-default-200 min-h-4
        // default-200 in HeroUI dark = ~zinc-800 (#27272a)
        <View
          style={{
            width: 1,
            flex: 1,
            minHeight: 16,
            backgroundColor: "#27272a",
          }}
        />
      )}
    </View>
  );

  // Web outer wrapper: flex items-stretch gap-2 (8px)
  if (!hasDetails) {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "stretch",
          gap: 8,
        }}
      >
        {iconColumn}
        {content}
      </View>
    );
  }

  return (
    <Pressable
      onPress={onToggle}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "stretch",
        gap: 8,
        opacity: pressed ? 0.6 : 1,
      })}
    >
      {iconColumn}
      {content}
    </Pressable>
  );
}

export function ToolCallsSection({ tool_calls_data }: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedCalls, setExpandedCalls] = useState<Set<number>>(new Set());

  const headerRotation = useSharedValue(-90);
  useEffect(() => {
    headerRotation.value = withTiming(isExpanded ? 0 : -90, { duration: 200 });
  }, [isExpanded, headerRotation]);
  const headerChevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${headerRotation.value}deg` }],
  }));

  const toggleCall = useCallback((index: number) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  if (!tool_calls_data || tool_calls_data.length === 0) return null;

  const label = `Used ${tool_calls_data.length} tool${tool_calls_data.length > 1 ? "s" : ""}`;

  return (
    // Web: w-fit max-w-140 (35rem = 560 CSS px). On a 390-CSS-px iPhone that's
    // almost the entire viewport, so on mobile we drop the cap entirely and
    // stretch to fill the chat column — anything narrower made the Input /
    // Output text wrap unreadably.
    <View style={{ alignSelf: "stretch", width: "100%" }}>
      <Pressable
        onPress={() => setIsExpanded((v) => !v)}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          opacity: pressed ? 0.6 : 1,
        })}
      >
        <StackedToolIcons calls={tool_calls_data} />
        <Text
          // Web: "Used N tools" → text-xs font-medium, parent text-zinc-500
          style={{
            fontSize: 12,
            color: "#71717a",
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
        {/* Web: chevron has ml-2 (8px gap from text), width/height 18 */}
        <Animated.View style={[headerChevronStyle, { marginLeft: 8 }]}>
          <AppIcon icon={ArrowDown01Icon} size={18} color="#71717a" />
        </Animated.View>
      </Pressable>
      {isExpanded && (
        // Web: <div className="space-y-0 py-2"> → 8px top/bottom, no row gap
        <View style={{ paddingTop: 8, paddingBottom: 8 }}>
          {tool_calls_data.map((call, index) => (
            <ToolCallItem
              key={call.tool_call_id || `${call.tool_name || "tool"}-${index}`}
              call={call}
              isLast={index === tool_calls_data.length - 1}
              isExpanded={expandedCalls.has(index)}
              onToggle={() => toggleCall(index)}
            />
          ))}
        </View>
      )}
    </View>
  );
}
