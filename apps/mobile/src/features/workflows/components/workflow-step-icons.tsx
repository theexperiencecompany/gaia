import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { WORKFLOW_COLORS } from "../constants/colors";

interface WorkflowStepIconsProps {
  steps: Array<{ category: string }>;
  /** Maximum number of distinct category badges to render before the "+N" overflow. */
  max?: number;
}

/**
 * Stacked, slightly-rotated category icons used as the visual "spine" of a
 * workflow card. Mirrors the web `WorkflowIcons` component (8°/-8° rotations,
 * max 3, "+N" overflow chip).
 */
export function WorkflowStepIcons({ steps, max = 3 }: WorkflowStepIconsProps) {
  const categories = [...new Set(steps.map((s) => s.category))];
  const display = categories.slice(0, max);

  if (display.length === 0) {
    return <View style={{ height: 32 }} />;
  }

  const overflow = categories.length - max;

  return (
    <View style={{ flexDirection: "row", alignItems: "center", height: 32 }}>
      {display.map((category, index) => {
        const iconElement = getToolCategoryIcon(category, {
          size: 16,
          showBackground: false,
        });
        const rotation =
          display.length > 1 ? (index % 2 === 0 ? "8deg" : "-8deg") : "0deg";

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
              transform: [{ rotate: rotation }],
              zIndex: index,
            }}
          >
            {iconElement ?? (
              <Text
                style={{
                  fontSize: 10,
                  color: WORKFLOW_COLORS.textMuted,
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
      {overflow > 0 ? (
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
          <Text style={{ fontSize: 10, color: WORKFLOW_COLORS.textMuted }}>
            +{overflow}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
