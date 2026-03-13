import { useState } from "react";
import { ActivityIndicator, Switch, View } from "react-native";
import { AppIcon, FlashIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Skill } from "../api/skills-api";
import { disableSkill, enableSkill } from "../api/skills-api";

interface SkillCardProps {
  skill: Skill;
  onToggle: (skill: Skill, enabled: boolean) => void;
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

export function SkillCard({ skill, onToggle }: SkillCardProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  const [isToggling, setIsToggling] = useState(false);

  const handleToggle = async (value: boolean) => {
    if (isToggling) return;
    setIsToggling(true);
    try {
      const success = value
        ? await enableSkill(skill.id)
        : await disableSkill(skill.id);
      if (success) {
        onToggle(skill, value);
      }
    } finally {
      setIsToggling(false);
    }
  };

  const categoryColor = getCategoryColor(skill.category);
  const categoryBg = getCategoryBg(skill.category);

  return (
    <View
      style={{
        backgroundColor: "rgba(23,25,32,1)",
        borderRadius: moderateScale(16, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      {/* Top row: icon + name + toggle */}
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
          <AppIcon icon={FlashIcon} size={20} color={categoryColor} />
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
            {skill.name}
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
                {formatCategoryLabel(skill.category)}
              </Text>
            </View>
          </View>
        </View>

        {isToggling ? (
          <ActivityIndicator size="small" color="#00bbff" />
        ) : (
          <Switch
            value={skill.enabled}
            onValueChange={(v) => void handleToggle(v)}
            trackColor={{ false: "rgba(255,255,255,0.1)", true: "#00bbff" }}
            thumbColor="#fff"
            ios_backgroundColor="rgba(255,255,255,0.1)"
          />
        )}
      </View>

      {/* Description */}
      {skill.description ? (
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#8e8e93",
            lineHeight: fontSize.xs * 1.5,
          }}
          numberOfLines={2}
        >
          {skill.description}
        </Text>
      ) : null}
    </View>
  );
}
