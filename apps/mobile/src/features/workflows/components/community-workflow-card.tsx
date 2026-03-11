import { Pressable, View } from "react-native";
import {
  AppIcon,
  Copy01Icon,
  PlayIcon,
  Tag01Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";
import type { CommunityWorkflow } from "../types/workflow-types";
import { formatRunCount } from "../utils/format-utils";

interface CommunityWorkflowCardProps {
  workflow: CommunityWorkflow;
  onPress?: (workflow: CommunityWorkflow) => void;
}

export function CommunityWorkflowCard({
  workflow,
  onPress,
}: CommunityWorkflowCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const runCountText = formatRunCount(workflow.total_executions ?? 0);

  return (
    <Pressable
      onPress={() => onPress?.(workflow)}
      style={({ pressed }) => ({
        borderRadius: moderateScale(24, 0.5),
        backgroundColor: pressed ? "rgba(63,63,70,0.5)" : "rgba(39,39,42,1)",
        padding: spacing.md,
        gap: spacing.sm,
      })}
    >
      {/* Step category icons */}
      <CommunityStepIcons steps={workflow.steps} />

      {/* Title + description */}
      <View>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "500",
            color: "#fff",
          }}
          numberOfLines={2}
        >
          {workflow.title}
        </Text>
        {workflow.description ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              marginTop: 4,
              lineHeight: 16,
            }}
            numberOfLines={2}
          >
            {workflow.description}
          </Text>
        ) : null}
      </View>

      {/* Category chips */}
      {workflow.categories && workflow.categories.length > 0 && (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {workflow.categories.slice(0, 3).map((cat) => (
            <View
              key={cat}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 3,
                paddingHorizontal: 7,
                paddingVertical: 2,
                borderRadius: 6,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            >
              <AppIcon icon={Tag01Icon} size={10} color="#71717a" />
              <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
                {cat}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Bottom row: run count + clone count + creator */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 2,
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          {/* Run count */}
          {runCountText !== "Never run" && (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              }}
            >
              <AppIcon icon={PlayIcon} size={13} color="#71717a" />
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                {runCountText}
              </Text>
            </View>
          )}

          {/* Clone count using total_executions as proxy when > 0 */}
          {(workflow.total_executions ?? 0) > 0 && (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              }}
            >
              <AppIcon icon={Copy01Icon} size={13} color="#71717a" />
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                {formatRunCount(workflow.total_executions ?? 0)} clones
              </Text>
            </View>
          )}
        </View>

        {/* Creator info */}
        {workflow.creator && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <AppIcon icon={UserCircle02Icon} size={18} color="#71717a" />
            <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
              {workflow.creator.name}
            </Text>
          </View>
        )}
      </View>
    </Pressable>
  );
}

function CommunityStepIcons({ steps }: { steps: Array<{ category: string }> }) {
  const categories = [...new Set(steps.map((s) => s.category))];
  const display = categories.slice(0, 3);

  if (display.length === 0) {
    return <View style={{ height: 32 }} />;
  }

  return (
    <View style={{ flexDirection: "row", alignItems: "center", height: 32 }}>
      {display.map((category, index) => {
        const iconElement = getToolCategoryIcon(category, {
          size: 16,
          showBackground: false,
        });
        return (
          <View
            key={category}
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(113,113,122,0.15)",
              alignItems: "center",
              justifyContent: "center",
              marginLeft: index > 0 ? -6 : 0,
              transform: [
                {
                  rotate:
                    display.length > 1
                      ? index % 2 === 0
                        ? "8deg"
                        : "-8deg"
                      : "0deg",
                },
              ],
              zIndex: index,
            }}
          >
            {iconElement ?? (
              <Text
                style={{
                  fontSize: 10,
                  color: "#a1a1aa",
                  fontWeight: "600",
                  textTransform: "uppercase",
                }}
                numberOfLines={1}
              >
                {category.slice(0, 2)}
              </Text>
            )}
          </View>
        );
      })}
      {categories.length > 3 && (
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            backgroundColor: "rgba(113,113,122,0.15)",
            alignItems: "center",
            justifyContent: "center",
            marginLeft: -6,
          }}
        >
          <Text style={{ fontSize: 10, color: "#a1a1aa" }}>
            +{categories.length - 3}
          </Text>
        </View>
      )}
    </View>
  );
}
