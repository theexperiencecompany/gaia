import * as Haptics from "expo-haptics";
import { ActivityIndicator, Pressable, View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import {
  AppIcon,
  PlayIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../../constants/colors";
import type { Workflow } from "../../types/workflow-types";

interface WorkflowDetailActionsProps {
  workflow: Workflow;
  isActivating: boolean;
  isExecuting: boolean;
  onToggleActivation: () => void;
  onExecute: () => void;
}

const ACTION_BUTTON_HEIGHT = 48;

/**
 * Detail header action row.
 *
 * Linear-style hierarchy: one full-width primary CTA (Run Now) plus a
 * low-emphasis Activate / Deactivate toggle stacked beneath it. Both share
 * the same 48pt height and corner radius — the only thing that varies is
 * background color (primary solid vs. neutral flat).
 */
export function WorkflowDetailActions({
  workflow,
  isActivating,
  isExecuting,
  onToggleActivation,
  onExecute,
}: WorkflowDetailActionsProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const handleToggle = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onToggleActivation();
  };

  const handleExecute = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onExecute();
  };

  const toggleIcon = workflow.activated ? ToggleOnIcon : ToggleOffIcon;
  const toggleLabel = workflow.activated ? "Deactivate" : "Activate";
  const toggleFg = workflow.activated
    ? WORKFLOW_COLORS.warningText
    : WORKFLOW_COLORS.textPrimary;

  const radius = moderateScale(14, 0.5);

  return (
    <View style={{ gap: 12 }}>
      <ActionButton
        label="Run Now"
        icon={PlayIcon}
        onPress={handleExecute}
        disabled={isExecuting}
        loading={isExecuting}
        backgroundColor={WORKFLOW_COLORS.primary}
        foregroundColor="#000"
        fontWeight="700"
        radius={radius}
        height={ACTION_BUTTON_HEIGHT}
        spacing={spacing.xs}
        fontSize={fontSize.sm}
      />

      <ActionButton
        label={toggleLabel}
        icon={toggleIcon}
        onPress={handleToggle}
        disabled={isActivating}
        loading={isActivating}
        backgroundColor={WORKFLOW_COLORS.surfaceMuted}
        foregroundColor={toggleFg}
        fontWeight="600"
        radius={radius}
        height={ACTION_BUTTON_HEIGHT}
        spacing={spacing.xs}
        fontSize={fontSize.sm}
      />
    </View>
  );
}

interface ActionButtonProps {
  label: string;
  icon: AnyIcon;
  onPress: () => void;
  disabled: boolean;
  loading: boolean;
  backgroundColor: string;
  foregroundColor: string;
  fontWeight: "600" | "700";
  radius: number;
  height: number;
  spacing: number;
  fontSize: number;
}

function ActionButton({
  label,
  icon,
  onPress,
  disabled,
  loading,
  backgroundColor,
  foregroundColor,
  fontWeight,
  radius,
  height,
  spacing,
  fontSize,
}: ActionButtonProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => ({
        height,
        borderRadius: radius,
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "row",
        gap: spacing,
        backgroundColor,
        opacity: pressed || disabled ? 0.85 : 1,
      })}
    >
      {loading ? (
        <ActivityIndicator size="small" color={foregroundColor} />
      ) : (
        <>
          <AppIcon icon={icon} size={15} color={foregroundColor} />
          <Text
            style={{
              fontSize,
              color: foregroundColor,
              fontWeight,
            }}
          >
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}
