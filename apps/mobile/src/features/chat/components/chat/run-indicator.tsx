import type {
  SelectedWorkflowDataOutput,
  TodoRunWake,
} from "@gaia/shared/api/generated";
import { describeTodoRunWake } from "@gaia/shared/todos";
import { View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FlashIcon,
  WorkflowSquare10Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";

// Gap scale tokens (decisions §5): 2/4/8/12/16/24.
const GAP_SM = 4;
const GAP_LG = 12;

const WAKE_ICONS = {
  schedule: Clock01Icon,
  trigger: FlashIcon,
  approval: CheckmarkCircle02Icon,
} satisfies Record<TodoRunWake["kind"], typeof Clock01Icon>;

/** The user's side of a run GAIA started on its own: what started it, as a chip. */
function RunIndicator({
  icon,
  label,
}: {
  icon: typeof Clock01Icon;
  label: string;
}) {
  const { fontSize, moderateScale } = useResponsive();

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        alignSelf: "flex-end",
        gap: GAP_SM,
        backgroundColor: colors.zinc700,
        borderRadius: moderateScale(12, 0.5),
        paddingHorizontal: GAP_LG,
        paddingVertical: GAP_SM,
      }}
    >
      <AppIcon
        icon={icon}
        size={moderateScale(14, 0.5)}
        color={colors.zinc300}
      />
      <Text style={{ fontSize: fontSize.sm, color: colors.zinc200 }}>
        {label}
      </Text>
    </View>
  );
}

/** What woke a tracked todo's run. */
export function TodoRunWakeIndicator({ wake }: { wake: TodoRunWake }) {
  return (
    <RunIndicator
      icon={WAKE_ICONS[wake.kind]}
      label={describeTodoRunWake(wake)}
    />
  );
}

/** The workflow a run was started for. */
export function WorkflowRunIndicator({
  workflow,
}: {
  workflow: SelectedWorkflowDataOutput;
}) {
  return <RunIndicator icon={WorkflowSquare10Icon} label={workflow.title} />;
}
