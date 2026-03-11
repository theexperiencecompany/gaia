import { View } from "react-native";
import { AppIcon, Settings02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Tool } from "../api/tools-api";

interface ToolCardProps {
  tool: Tool;
}

function getCategoryColor(category: string): string {
  const colors: Record<string, string> = {
    productivity: "#00bbff",
    communication: "#34c759",
    developer: "#af52de",
    analytics: "#ff9500",
    finance: "#32ade6",
    "ai-ml": "#ff375f",
    education: "#5ac8fa",
    personal: "#ffcc00",
    search: "#00bbff",
    web: "#34c759",
    file: "#ff9500",
    calendar: "#32ade6",
    memory: "#af52de",
    other: "#8e8e93",
  };
  return colors[category] ?? "#8e8e93";
}

function getCategoryBg(category: string): string {
  const bgs: Record<string, string> = {
    productivity: "rgba(0,187,255,0.12)",
    communication: "rgba(52,199,89,0.12)",
    developer: "rgba(175,82,222,0.12)",
    analytics: "rgba(255,149,0,0.12)",
    finance: "rgba(50,173,230,0.12)",
    "ai-ml": "rgba(255,55,95,0.12)",
    education: "rgba(90,200,250,0.12)",
    personal: "rgba(255,204,0,0.12)",
    search: "rgba(0,187,255,0.12)",
    web: "rgba(52,199,89,0.12)",
    file: "rgba(255,149,0,0.12)",
    calendar: "rgba(50,173,230,0.12)",
    memory: "rgba(175,82,222,0.12)",
    other: "rgba(142,142,147,0.12)",
  };
  return bgs[category] ?? "rgba(142,142,147,0.12)";
}

function formatCategoryLabel(category: string): string {
  if (category === "ai-ml") return "AI & ML";
  return category
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function ToolCard({ tool }: ToolCardProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  const categoryColor = getCategoryColor(tool.category);
  const categoryBg = getCategoryBg(tool.category);

  return (
    <View
      style={{
        backgroundColor: "rgba(23,25,32,1)",
        borderRadius: moderateScale(16, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      {/* Top row: icon + name + category badge */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <View
          style={{
            width: 40,
            height: 40,
            borderRadius: moderateScale(10, 0.5),
            backgroundColor: categoryBg,
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <AppIcon icon={Settings02Icon} size={20} color={categoryColor} />
        </View>

        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#f4f4f5",
            }}
            numberOfLines={1}
          >
            {tool.name}
          </Text>
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              marginTop: 2,
            }}
          >
            <View
              style={{
                backgroundColor: categoryBg,
                borderRadius: 6,
                paddingHorizontal: 6,
                paddingVertical: 2,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: categoryColor,
                  fontWeight: "500",
                }}
              >
                {formatCategoryLabel(tool.category)}
              </Text>
            </View>
            {tool.integrationName ? (
              <Text
                style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}
                numberOfLines={1}
              >
                via {tool.integrationName}
              </Text>
            ) : null}
          </View>
        </View>
      </View>

      {/* Description */}
      {tool.description ? (
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#8e8e93",
            lineHeight: fontSize.xs * 1.5,
          }}
          numberOfLines={2}
        >
          {tool.description}
        </Text>
      ) : null}
    </View>
  );
}
