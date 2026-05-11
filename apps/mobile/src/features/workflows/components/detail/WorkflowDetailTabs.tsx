import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../../constants/colors";

export type WorkflowDetailTab = "steps" | "history";

interface WorkflowDetailTabsProps {
  activeTab: WorkflowDetailTab;
  onChange: (tab: WorkflowDetailTab) => void;
  stepsCount: number;
  historyCount?: number;
}

interface TabConfig {
  key: WorkflowDetailTab;
  label: string;
  count?: number;
}

export function WorkflowDetailTabs({
  activeTab,
  onChange,
  stepsCount,
  historyCount,
}: WorkflowDetailTabsProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const tabs: TabConfig[] = [
    { key: "steps", label: "Steps", count: stepsCount },
    { key: "history", label: "History", count: historyCount },
  ];

  return (
    <View
      style={{
        flexDirection: "row",
        gap: spacing.xs,
        backgroundColor: WORKFLOW_COLORS.surfaceTinted,
        borderRadius: moderateScale(12, 0.5),
        padding: 4,
      }}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.key;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onChange(tab.key)}
            style={{
              flex: 1,
              paddingVertical: 8,
              borderRadius: moderateScale(10, 0.5),
              alignItems: "center",
              backgroundColor: isActive
                ? WORKFLOW_COLORS.cardBgActive
                : "transparent",
            }}
          >
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: isActive ? "600" : "400",
                  color: isActive
                    ? WORKFLOW_COLORS.textPrimary
                    : WORKFLOW_COLORS.textFaint,
                }}
              >
                {tab.label}
              </Text>
              {tab.count !== undefined && tab.count > 0 ? (
                <View
                  style={{
                    borderRadius: 999,
                    backgroundColor: isActive
                      ? "rgba(0,187,255,0.20)"
                      : "rgba(255,255,255,0.08)",
                    paddingHorizontal: 6,
                    paddingVertical: 0,
                    minWidth: 22,
                    height: 16,
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      lineHeight: 14,
                      color: isActive
                        ? WORKFLOW_COLORS.primary
                        : WORKFLOW_COLORS.textFaint,
                      fontWeight: "600",
                      includeFontPadding: false,
                      textAlignVertical: "center",
                    }}
                  >
                    {tab.count}
                  </Text>
                </View>
              ) : null}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}
