import { Card } from "heroui-native";
import { Pressable, View } from "react-native";
import { AppIcon, PlayIcon, UserCircle02Icon } from "@/components/icons";
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
      style={{ borderRadius: moderateScale(24, 0.5) }}
    >
      {({ pressed }) => (
        <Card
          variant="secondary"
          style={{
            borderRadius: moderateScale(24, 0.5),
            backgroundColor: pressed
              ? "rgba(63,63,70,0.5)"
              : "rgba(39,39,42,1)",
            overflow: "hidden",
          }}
        >
          <Card.Body
            style={{
              padding: spacing.md,
              gap: spacing.sm,
            }}
          >
            <CommunityStepIcons steps={workflow.steps} />

            <View>
              <Card.Title
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "500",
                  color: "#fff",
                }}
                numberOfLines={2}
              >
                {workflow.title}
              </Card.Title>
              {workflow.description ? (
                <Card.Description
                  style={{
                    fontSize: fontSize.xs,
                    color: "#71717a",
                    marginTop: 4,
                    lineHeight: 16,
                  }}
                  numberOfLines={2}
                >
                  {workflow.description}
                </Card.Description>
              ) : null}
            </View>

            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                marginTop: 2,
              }}
            >
              {runCountText !== "Never run" && (
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <AppIcon icon={PlayIcon} size={14} color="#71717a" />
                  <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                    {runCountText}
                  </Text>
                </View>
              )}

              {workflow.creator && (
                <View
                  style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
                >
                  <AppIcon icon={UserCircle02Icon} size={20} color="#71717a" />
                  <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
                    {workflow.creator.name}
                  </Text>
                </View>
              )}
            </View>
          </Card.Body>
        </Card>
      )}
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
