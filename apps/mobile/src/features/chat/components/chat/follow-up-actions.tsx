import * as Haptics from "expo-haptics";
import { Pressable, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface FollowUpActionsProps {
  actions: string[];
  onActionPress?: (action: string) => void;
}

/** Suggestion chips shown below a finished AI turn. */
export function FollowUpActions({
  actions,
  onActionPress,
}: FollowUpActionsProps) {
  const { spacing } = useResponsive();
  if (!actions.length) return null;

  return (
    <View
      className="flex-row flex-wrap gap-2 mt-2"
      style={{ paddingLeft: spacing.md, paddingRight: spacing.md }}
    >
      {actions.map((action, i) => (
        <Animated.View
          key={action}
          entering={FadeInDown.delay(i * 60)
            .duration(300)
            .springify()}
        >
          <Pressable
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              onActionPress?.(action);
            }}
            className="px-3.5 py-1.5 rounded-full bg-zinc-800 active:bg-zinc-700"
          >
            <Text className="text-zinc-300 text-sm">{action}</Text>
          </Pressable>
        </Animated.View>
      ))}
    </View>
  );
}
