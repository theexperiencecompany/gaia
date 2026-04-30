import { normalizeCategoryName } from "@gaia/shared/icons";
import { useEffect, useRef, useState } from "react";
import { Animated, LayoutAnimation, Pressable, View } from "react-native";
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

const CONNECTOR_COLOR = "#3f3f46";
const TEXT_MUTED = "#a1a1aa";
const TEXT_DIM = "#71717a";
const TEXT_STRONG = "#d4d4d8";
const DETAILS_BG = "rgba(39, 39, 42, 0.5)"; // bg-zinc-800/50

function formatToolName(toolName: string): string {
  return toolName
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\s+tool$/i, "")
    .trim();
}

function formatCategoryLabel(category: string): string {
  return category
    .replace(/_/g, " ")
    .split(" ")
    .map(
      (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
    )
    .join(" ");
}

function PulsingDot({ color, size = 6 }: { color: string; size?: number }) {
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.3,
          duration: 600,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 1,
          duration: 600,
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={{
        opacity,
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: color,
      }}
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
    return (
      <AppIcon icon={CheckmarkCircle01Icon} size={12} color="#34d399" />
    );
  }
  return <AppIcon icon={Cancel01Icon} size={12} color="#f87171" />;
}

function ToolIcon({
  category,
  iconUrl,
  size = 20,
}: {
  category: string;
  iconUrl?: string;
  size?: number;
}) {
  const icon = getToolCategoryIcon(
    category,
    { size, showBackground: true },
    iconUrl,
  );
  if (icon) return icon;
  return (
    <View
      style={{
        padding: 4,
        backgroundColor: "#27272a",
        borderRadius: 8,
      }}
    >
      <AppIcon icon={ToolsIcon} size={size} color={TEXT_MUTED} />
    </View>
  );
}

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
            minWidth: 28,
            alignItems: "center",
            justifyContent: "center",
            transform: [
              {
                rotate: index % 2 === 0 ? "8deg" : "-8deg",
              },
            ],
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
            width: 26,
            height: 26,
            borderRadius: 8,
            backgroundColor: "rgba(63, 63, 70, 0.6)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text
            style={{
              fontSize: 10,
              color: TEXT_MUTED,
              fontWeight: "500",
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
}: {
  call: ToolCallEntry;
  isLast: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const chevronRotation = useRef(new Animated.Value(0)).current;

  const hasInputs =
    call.inputs &&
    typeof call.inputs === "object" &&
    Object.keys(call.inputs).length > 0;
  const hasOutput = call.output && call.output.trim().length > 0;
  const hasDetails = hasInputs || hasOutput;

  const hasCategoryText =
    call.show_category !== false &&
    call.tool_category &&
    call.tool_category !== "unknown";

  const displayName = call.message || formatToolName(call.tool_name || "Tool");

  const categoryLabel = call.integration_name
    ? call.integration_name
    : call.tool_category
      ? formatCategoryLabel(call.tool_category)
      : null;

  const toggle = () => {
    if (!hasDetails) return;
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setIsExpanded((prev) => {
      const next = !prev;
      Animated.timing(chevronRotation, {
        toValue: next ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }).start();
      return next;
    });
  };

  const chevronRotate = chevronRotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "180deg"],
  });

  return (
    <View style={{ flexDirection: "row", alignItems: "stretch", gap: 8 }}>
      {/* Timeline rail: icon + connector line */}
      <View style={{ alignItems: "center", alignSelf: "stretch" }}>
        <View
          style={{
            minHeight: 32,
            minWidth: 32,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ToolIcon
            category={call.tool_category || "general"}
            iconUrl={call.icon_url}
            size={21}
          />
        </View>
        {!isLast && (
          <View
            style={{
              width: 1,
              flex: 1,
              backgroundColor: CONNECTOR_COLOR,
              minHeight: 16,
            }}
          />
        )}
      </View>

      {/* Body */}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Pressable
          onPress={toggle}
          disabled={!hasDetails}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            paddingTop: hasCategoryText ? 0 : 8,
            opacity: pressed && hasDetails ? 0.7 : 1,
          })}
        >
          <Text
            style={{
              fontSize: 12,
              color: TEXT_MUTED,
              fontWeight: "500",
              flexShrink: 1,
            }}
            numberOfLines={2}
          >
            {displayName}
          </Text>
          {hasDetails && (
            <Animated.View
              style={{ transform: [{ rotate: chevronRotate }] }}
            >
              <AppIcon icon={ArrowDown01Icon} size={14} color={TEXT_DIM} />
            </Animated.View>
          )}
          <View style={{ marginLeft: "auto", paddingLeft: 6 }}>
            <StatusIndicator status={call.status} />
          </View>
        </Pressable>

        {hasCategoryText && categoryLabel && (
          <Text
            style={{
              fontSize: 11,
              color: TEXT_DIM,
              marginTop: 1,
            }}
          >
            {categoryLabel}
          </Text>
        )}

        {isExpanded && hasDetails && (
          <View
            style={{
              marginTop: 8,
              marginBottom: 12,
              backgroundColor: DETAILS_BG,
              borderRadius: 12,
              padding: 12,
              gap: 8,
            }}
          >
            {hasInputs && (
              <View>
                <Text
                  style={{
                    fontSize: 11,
                    color: TEXT_DIM,
                    fontWeight: "500",
                    marginBottom: 4,
                  }}
                >
                  Input
                </Text>
                <Text
                  style={{ fontSize: 11, color: TEXT_STRONG }}
                  numberOfLines={8}
                >
                  {JSON.stringify(call.inputs, null, 2)}
                </Text>
              </View>
            )}
            {hasOutput && (
              <View>
                <Text
                  style={{
                    fontSize: 11,
                    color: TEXT_DIM,
                    fontWeight: "500",
                    marginBottom: 4,
                  }}
                >
                  Output
                </Text>
                <Text
                  style={{ fontSize: 11, color: TEXT_STRONG }}
                  numberOfLines={12}
                >
                  {call.output}
                </Text>
              </View>
            )}
          </View>
        )}
      </View>
    </View>
  );
}

export function ToolCallsSection({ tool_calls_data }: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const chevronRotation = useRef(new Animated.Value(0)).current;

  if (!tool_calls_data || tool_calls_data.length === 0) return null;

  const hasRunning = tool_calls_data.some(
    (call) => !call.status || call.status === "running",
  );

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setIsExpanded((prev) => {
      const next = !prev;
      Animated.timing(chevronRotation, {
        toValue: next ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }).start();
      return next;
    });
  };

  const chevronRotate = chevronRotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "180deg"],
  });

  const count = tool_calls_data.length;

  return (
    <View style={{ alignSelf: "flex-start", maxWidth: 560 }}>
      <Pressable
        onPress={toggle}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          paddingVertical: 2,
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <StackedToolIcons calls={tool_calls_data} />
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          {hasRunning && <PulsingDot color="#60a5fa" />}
          <Text
            style={{
              fontSize: 12,
              color: TEXT_DIM,
              fontWeight: "500",
            }}
          >
            Used {count} tool{count > 1 ? "s" : ""}
          </Text>
        </View>
        <Animated.View
          style={{
            marginLeft: 8,
            transform: [{ rotate: chevronRotate }],
          }}
        >
          <AppIcon icon={ArrowDown01Icon} size={16} color={TEXT_DIM} />
        </Animated.View>
      </Pressable>

      {isExpanded && (
        <View style={{ paddingVertical: 8 }}>
          {tool_calls_data.map((call, index) => (
            <ToolCallItem
              key={
                call.tool_call_id || `${call.tool_name || "tool"}-${index}`
              }
              call={call}
              isLast={index === tool_calls_data.length - 1}
            />
          ))}
        </View>
      )}
    </View>
  );
}
