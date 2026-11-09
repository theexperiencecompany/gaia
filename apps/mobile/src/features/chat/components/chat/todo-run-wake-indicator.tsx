import type { TodoRunWake } from "@gaia/shared/api/generated";
import { describeTodoRunWake } from "@gaia/shared/todos";
import { View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FlashIcon,
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

/** The user's side of a tracked todo's run: what woke it, as a workflow run shows its card. */
export function TodoRunWakeIndicator({ wake }: { wake: TodoRunWake }) {
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
        icon={WAKE_ICONS[wake.kind]}
        size={moderateScale(14, 0.5)}
        color={colors.zinc300}
      />
      <Text style={{ fontSize: fontSize.sm, color: colors.zinc200 }}>
        {describeTodoRunWake(wake)}
      </Text>
    </View>
  );
}
