import { normalizeCategoryName } from "@gaia/shared/icons";
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowDown01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  ToolsIcon,
} from "@/components/icons";
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

function formatInputValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length === 0
      ? "[]"
      : `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  return JSON.stringify(value);
}

function PulsingDot({ color }: { color: string }) {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.3, { duration: 600 }),
        withTiming(1, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        animatedStyle,
        {
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: color,
        },
      ]}
    />
  );
}

function StatusIndicator({
  status,
}: {
  status?: "running" | "done" | "error";
}) {
  if (!status || status === "running") {
    return <PulsingDot color="#60a5fa" />;
  }
  if (status === "done") {
    return <AppIcon icon={CheckmarkCircle01Icon} size={14} color="#34d399" />;
  }
  return <AppIcon icon={Cancel01Icon} size={14} color="#f87171" />;
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

const MAX_STACKED_ICONS = 6;

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

  if (displayIcons.length <= 1) return null;

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        marginRight: 6,
      }}
    >
      {displayIcons.map((call, index) => (
        <View
          key={`${call.tool_name || "tool"}-${index}`}
          style={{
            marginLeft: index === 0 ? 0 : -6,
            zIndex: index,
            transform: [{ rotate: index % 2 === 0 ? "8deg" : "-8deg" }],
          }}
        >
          <ToolIcon
            category={call.tool_category || "general"}
            iconUrl={call.icon_url}
            size={18}
          />
        </View>
      ))}
      {overflow > 0 && (
        <View
          style={{
            marginLeft: -6,
            width: 28,
            height: 28,
            borderRadius: 8,
            backgroundColor: "rgba(63,63,70,0.6)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text
            style={{
              fontSize: 10,
              color: "#a1a1aa",
              fontWeight: "600",
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
  const hasOutput = call.output && call.output.trim().length > 0;
  const hasDetails = !!(hasInputs || hasOutput);

  const hasCategoryText =
    call.show_category !== false &&
    call.tool_category &&
    call.tool_category !== "unknown";

  const displayName = call.message || formatToolName(call.tool_name || "Tool");

  const categoryLabel = call.integration_name
    ? call.integration_name
    : call.tool_category
      ? call.tool_category
          .replace(/_/g, " ")
          .split(" ")
          .map(
            (word) =>
              word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
          )
          .join(" ")
      : null;

  const rotation = useSharedValue(isExpanded ? 0 : -90);
  useEffect(() => {
    rotation.value = withTiming(isExpanded ? 0 : -90, { duration: 200 });
  }, [isExpanded, rotation]);
  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  const headerRow = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
      }}
    >
      <Text
        style={{
          fontSize: 14,
          color: "#d4d4d8",
          fontWeight: "500",
          flex: 1,
          lineHeight: 18,
        }}
        numberOfLines={2}
      >
        {displayName}
      </Text>
      <StatusIndicator status={call.status} />
      {hasDetails && (
        <Animated.View style={chevronStyle}>
          <AppIcon icon={ArrowDown01Icon} size={16} color="#71717a" />
        </Animated.View>
      )}
    </View>
  );

  const content = (
    <View style={{ flex: 1, minWidth: 0, paddingTop: 6 }}>
      {headerRow}
      {hasCategoryText && categoryLabel && (
        <Text
          style={{
            fontSize: 12,
            color: "#71717a",
            marginTop: 2,
          }}
        >
          {categoryLabel}
        </Text>
      )}
      {hasDetails && isExpanded && (
        <View
          style={{
            marginTop: 10,
            marginBottom: 6,
            backgroundColor: "rgba(24,24,27,0.6)",
            borderRadius: 12,
            paddingHorizontal: 12,
            paddingVertical: 10,
            gap: 12,
          }}
        >
          {hasInputs && (
            <View style={{ gap: 6 }}>
              <Text
                style={{
                  fontSize: 12,
                  color: "#71717a",
                  fontWeight: "500",
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Input
              </Text>
              <View style={{ gap: 4 }}>
                {Object.entries(call.inputs ?? {}).map(([key, value]) => (
                  <View key={key} style={{ gap: 2 }}>
                    <Text
                      style={{
                        fontSize: 12,
                        color: "#71717a",
                      }}
                    >
                      {key}
                    </Text>
                    <Text
                      style={{
                        fontSize: 13,
                        color: "#e4e4e7",
                        lineHeight: 18,
                      }}
                    >
                      {formatInputValue(value)}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}
          {hasOutput && (
            <View style={{ gap: 6 }}>
              <Text
                style={{
                  fontSize: 12,
                  color: "#71717a",
                  fontWeight: "500",
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                Output
              </Text>
              <Text
                style={{
                  fontSize: 13,
                  color: "#e4e4e7",
                  lineHeight: 18,
                }}
                numberOfLines={12}
              >
                {call.output}
              </Text>
            </View>
          )}
        </View>
      )}
    </View>
  );

  const iconColumn = (
    <View style={{ alignItems: "center", alignSelf: "stretch" }}>
      <View
        style={{
          width: 32,
          height: 32,
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <ToolIcon
          category={call.tool_category || "general"}
          iconUrl={call.icon_url}
          size={20}
        />
      </View>
      {!isLast && (
        <View
          style={{
            width: 1,
            flex: 1,
            minHeight: 8,
            backgroundColor: "rgba(228,228,231,0.15)",
            marginTop: 2,
          }}
        />
      )}
    </View>
  );

  if (!hasDetails) {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "stretch",
          gap: 10,
          paddingVertical: 6,
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
        gap: 10,
        paddingVertical: 6,
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

  const hasRunning = tool_calls_data.some(
    (call) => !call.status || call.status === "running",
  );

  const label = hasRunning
    ? `Using ${tool_calls_data.length} tool${tool_calls_data.length > 1 ? "s" : ""}`
    : `Used ${tool_calls_data.length} tool${tool_calls_data.length > 1 ? "s" : ""}`;

  return (
    <View style={{ width: "100%", maxWidth: 560, paddingHorizontal: 16 }}>
      <Pressable
        onPress={() => setIsExpanded((v) => !v)}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingVertical: 8,
          opacity: pressed ? 0.6 : 1,
        })}
      >
        <StackedToolIcons calls={tool_calls_data} />
        <Text
          style={{
            fontSize: 14,
            color: "#a1a1aa",
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
        <Animated.View style={headerChevronStyle}>
          <AppIcon icon={ArrowDown01Icon} size={16} color="#71717a" />
        </Animated.View>
      </Pressable>
      {isExpanded && (
        <View style={{ paddingTop: 4, paddingBottom: 4 }}>
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
