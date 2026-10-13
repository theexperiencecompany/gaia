import type { WorkflowDelivery } from "@gaia/shared/api/generated";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../constants/colors";

interface DeliveryModeTabsProps {
  /** null until the user picks one; a new workflow cannot be created without it. */
  value: WorkflowDelivery | null;
  onChange: (delivery: WorkflowDelivery) => void;
}

const TABS: { key: WorkflowDelivery; label: string }[] = [
  { key: "now", label: "Tell me now" },
  { key: "brief", label: "Add to my brief" },
  { key: "silent", label: "Don't notify me" },
];

/**
 * How each run's result reaches the user, mirroring the web workflow modal's
 * delivery control: nothing is preselected, the choice is the user's.
 */
export function DeliveryModeTabs({ value, onChange }: DeliveryModeTabsProps) {
  const { fontSize, moderateScale } = useResponsive();

  return (
    <View
      accessibilityRole="radiogroup"
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
            accessibilityRole="radio"
            accessibilityState={{ selected: isActive }}
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
                fontSize: fontSize.xs,
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
