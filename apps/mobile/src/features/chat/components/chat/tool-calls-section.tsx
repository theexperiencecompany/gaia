import { normalizeCategoryName } from "@gaia/shared/icons";
import {
  Accordion,
  Card,
  Chip,
  Divider,
  Spinner,
  Surface,
} from "heroui-native";
import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
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
    return (
      <Chip size="sm" variant="soft" color="accent">
        <Spinner size="sm" color="default" />
      </Chip>
    );
  }
  if (status === "done") {
    return (
      <Chip size="sm" variant="soft" color="success">
        <AppIcon icon={CheckmarkCircle01Icon} size={12} color="#34d399" />
      </Chip>
    );
  }
  return (
    <Chip size="sm" variant="soft" color="danger">
      <AppIcon icon={Cancel01Icon} size={12} color="#f87171" />
    </Chip>
  );
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
      <AppIcon icon={ToolsIcon} size={size} color="#a1a1aa" />
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
            transform: [
              {
                rotate:
                  displayIcons.length > 1
                    ? index % 2 === 0
                      ? "8deg"
                      : "-8deg"
                    : "0deg",
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
            borderRadius: 6,
            backgroundColor: "#3f3f46",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text
            style={{
              fontSize: 9,
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
}: {
  call: ToolCallEntry;
  isLast: boolean;
}) {
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
      ? call.tool_category
          .replace(/_/g, " ")
          .split(" ")
          .map(
            (word) =>
              word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
          )
          .join(" ")
      : null;

  const itemValue = call.tool_call_id || `${call.tool_name || "tool"}`;

  if (!hasDetails) {
    return (
      <>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingVertical: 8,
            paddingHorizontal: 4,
          }}
        >
          <ToolIcon
            category={call.tool_category || "general"}
            iconUrl={call.icon_url}
            size={18}
          />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text
              style={{
                fontSize: 12,
                color: "#a1a1aa",
                fontWeight: "500",
              }}
              numberOfLines={2}
            >
              {displayName}
            </Text>
            {hasCategoryText && categoryLabel && (
              <Text
                style={{
                  fontSize: 10,
                  color: "#71717a",
                  marginTop: 1,
                }}
              >
                {categoryLabel}
              </Text>
            )}
          </View>
          <StatusIndicator status={call.status} />
        </View>
        {!isLast && <Divider />}
      </>
    );
  }

  return (
    <>
      <Accordion selectionMode="single" isDividerVisible={false}>
        <Accordion.Item value={itemValue}>
          <Accordion.Trigger className="flex-row items-center gap-2 px-1 py-2">
            <ToolIcon
              category={call.tool_category || "general"}
              iconUrl={call.icon_url}
              size={18}
            />
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text
                style={{
                  fontSize: 12,
                  color: "#a1a1aa",
                  fontWeight: "500",
                }}
                numberOfLines={2}
              >
                {displayName}
              </Text>
              {hasCategoryText && categoryLabel && (
                <Text
                  style={{
                    fontSize: 10,
                    color: "#71717a",
                    marginTop: 1,
                  }}
                >
                  {categoryLabel}
                </Text>
              )}
            </View>
            <StatusIndicator status={call.status} />
            <Accordion.Indicator iconProps={{ size: 12, color: "#71717a" }} />
          </Accordion.Trigger>
          <Accordion.Content>
            <Surface
              variant="secondary"
              style={{
                borderRadius: 10,
                padding: 10,
                gap: 6,
                marginBottom: 4,
              }}
            >
              {hasInputs && (
                <View>
                  <Text
                    style={{
                      fontSize: 10,
                      color: "#71717a",
                      fontWeight: "500",
                      marginBottom: 3,
                    }}
                  >
                    Input
                  </Text>
                  <Text
                    style={{ fontSize: 11, color: "#d4d4d8" }}
                    numberOfLines={6}
                  >
                    {JSON.stringify(call.inputs, null, 2)}
                  </Text>
                </View>
              )}
              {hasOutput && (
                <View>
                  <Text
                    style={{
                      fontSize: 10,
                      color: "#71717a",
                      fontWeight: "500",
                      marginBottom: 3,
                    }}
                  >
                    Output
                  </Text>
                  <Text
                    style={{ fontSize: 11, color: "#d4d4d8" }}
                    numberOfLines={10}
                  >
                    {call.output}
                  </Text>
                </View>
              )}
            </Surface>
          </Accordion.Content>
        </Accordion.Item>
      </Accordion>
      {!isLast && <Divider />}
    </>
  );
}

export function ToolCallsSection({ tool_calls_data }: ToolCallsSectionProps) {
  if (!tool_calls_data || tool_calls_data.length === 0) return null;

  const hasRunning = tool_calls_data.some(
    (call) => !call.status || call.status === "running",
  );

  return (
    <Accordion selectionMode="single" isDividerVisible={false}>
      <Accordion.Item value="tool-calls">
        <Accordion.Trigger className="flex-row items-center gap-1.5 py-1">
          <StackedToolIcons calls={tool_calls_data} />
          <View className="flex-row items-center gap-1">
            {hasRunning && <PulsingDot color="#60a5fa" />}
            <Text
              style={{
                fontSize: 12,
                color: "#71717a",
                fontWeight: "500",
              }}
            >
              Used {tool_calls_data.length} tool
              {tool_calls_data.length > 1 ? "s" : ""}
            </Text>
          </View>
          <Accordion.Indicator iconProps={{ size: 16, color: "#71717a" }} />
        </Accordion.Trigger>
        <Accordion.Content>
          <Card
            variant="secondary"
            className="rounded-2xl mt-1 overflow-hidden"
          >
            <Card.Body className="py-2 px-3">
              {tool_calls_data.map((call, index) => (
                <ToolCallItem
                  key={
                    call.tool_call_id || `${call.tool_name || "tool"}-${index}`
                  }
                  call={call}
                  isLast={index === tool_calls_data.length - 1}
                />
              ))}
            </Card.Body>
          </Card>
        </Accordion.Content>
      </Accordion.Item>
    </Accordion>
  );
}
