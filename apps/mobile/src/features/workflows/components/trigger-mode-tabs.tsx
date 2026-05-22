import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../constants/colors";

export type TriggerMode = "manual" | "schedule" | "trigger";

interface TriggerModeTabsProps {
  value: TriggerMode;
  onChange: (mode: TriggerMode) => void;
}

const TABS: { key: TriggerMode; label: string }[] = [
  { key: "manual", label: "Manual" },
  { key: "schedule", label: "Schedule" },
  { key: "trigger", label: "Trigger" },
];

/**
 * Three-tab trigger-mode switcher mirroring the web `WorkflowTriggerSection`
 * panel. Manual = run on demand; Schedule = cron-based; Trigger = integration
 * event (Gmail / Slack / GitHub / ...) configured via the dynamic schema form.
 */
export function TriggerModeTabs({ value, onChange }: TriggerModeTabsProps) {
  const { fontSize, moderateScale } = useResponsive();

  return (
    <View
      style={{
        flexDirection: "row",
        backgroundColor: WORKFLOW_COLORS.surfaceTinted,
        borderRadius: moderateScale(12, 0.5),
        padding: 4,
        gap: 4,
      }}
    >
      {TABS.map((tab) => {
        const isActive = tab.key === value;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onChange(tab.key)}
            style={{
              flex: 1,
              paddingVertical: 10,
              borderRadius: moderateScale(10, 0.5),
              alignItems: "center",
              backgroundColor: isActive
                ? WORKFLOW_COLORS.cardBgActive
                : "transparent",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: isActive ? "600" : "500",
                color: isActive
                  ? WORKFLOW_COLORS.textPrimary
                  : WORKFLOW_COLORS.textFaint,
              }}
            >
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
