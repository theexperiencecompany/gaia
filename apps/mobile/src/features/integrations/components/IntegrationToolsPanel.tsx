import { Pressable, View } from "react-native";
import Animated, {
  type SharedValue,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, ArrowDown01Icon, Wrench01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { IntegrationTool } from "../types";

interface IntegrationToolsPanelProps {
  tools: IntegrationTool[];
  initialCount?: number;
}

function ToolItem({ tool }: { tool: IntegrationTool }) {
  const { fontSize, spacing } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        paddingVertical: spacing.xs,
      }}
    >
      <View
        style={{
          width: 4,
          height: 4,
          borderRadius: 2,
          backgroundColor: "#00bbff",
          marginTop: 7,
          flexShrink: 0,
        }}
      />
      <View style={{ flex: 1 }}>
        <Text
          className="text-zinc-200"
          style={{ fontSize: fontSize.sm, fontWeight: "500" }}
        >
          {tool.name}
        </Text>
        {tool.description ? (
          <Text
            className="text-zinc-500"
            style={{ fontSize: fontSize.xs, marginTop: 2 }}
          >
            {tool.description}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

/**
 * Collapsible tools list with chevron toggle. Mirrors the web "Show more /
 * Show less" pattern using a Reanimated rotating chevron.
 */
export function IntegrationToolsPanel({
  tools,
  initialCount = 5,
}: IntegrationToolsPanelProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();

  const expanded = useSharedValue(0);
  const visibleTools =
    tools.length > initialCount ? tools.slice(0, initialCount) : tools;
  const hiddenTools =
    tools.length > initialCount ? tools.slice(initialCount) : [];
  const hasMore = hiddenTools.length > 0;

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${expanded.value * 180}deg` }],
  }));

  const onToggle = () => {
    expanded.value = withTiming(expanded.value === 0 ? 1 : 0, {
      duration: 200,
    });
  };

  if (tools.length === 0) {
    return null;
  }

  return (
    <View
      className="bg-white/[0.04]"
      style={{
        borderRadius: moderateScale(14, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <AppIcon icon={Wrench01Icon} size={14} color="#71717a" />
        <Text
          className="uppercase tracking-wider text-zinc-500"
          style={{ fontSize: fontSize.xs, fontWeight: "600" }}
        >
          Available Tools
        </Text>
        <View
          className="items-center justify-center bg-primary/10"
          style={{
            borderRadius: 999,
            minWidth: 20,
            height: 18,
            paddingHorizontal: 6,
          }}
        >
          <Text
            className="text-primary"
            style={{
              fontSize: fontSize.xs - 1,
              fontWeight: "600",
            }}
          >
            {tools.length}
          </Text>
        </View>
      </View>

      <View style={{ gap: 2 }}>
        {visibleTools.map((tool) => (
          <ToolItem key={tool.name} tool={tool} />
        ))}
        {hasMore ? (
          <HiddenTools tools={hiddenTools} expanded={expanded} />
        ) : null}
      </View>

      {hasMore ? (
        <Pressable
          onPress={onToggle}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            gap: 4,
            paddingVertical: spacing.xs,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <Text
            className="text-primary"
            style={{ fontSize: fontSize.xs, fontWeight: "500" }}
          >
            Show {hiddenTools.length} more tools
          </Text>
          <Animated.View style={chevronStyle}>
            <AppIcon icon={ArrowDown01Icon} size={12} color="#00bbff" />
          </Animated.View>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * Tools that animate from collapsed to expanded. Renders nothing when the
 * shared value is 0 to avoid pushing layout while collapsed.
 */
function HiddenTools({
  tools,
  expanded,
}: {
  tools: IntegrationTool[];
  expanded: SharedValue<number>;
}) {
  const animatedStyle = useAnimatedStyle(() => ({
    opacity: expanded.value,
    height: expanded.value === 0 ? 0 : undefined,
    overflow: "hidden",
  }));

  return (
    <Animated.View style={animatedStyle}>
      {tools.map((tool) => (
        <ToolItem key={tool.name} tool={tool} />
      ))}
    </Animated.View>
  );
}
