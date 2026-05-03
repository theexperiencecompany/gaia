import { Spinner } from "heroui-native";
import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface LoadingIndicatorProps {
  progress?: string;
}

export function LoadingIndicator({ progress }: LoadingIndicatorProps) {
  const { spacing, fontSize } = useResponsive();

  const translateY = useSharedValue(8);
  const opacity = useSharedValue(0);

  useEffect(() => {
    translateY.value = 8;
    opacity.value = 0;
    translateY.value = withTiming(0, { duration: 200 });
    opacity.value = withTiming(1, { duration: 200 });
  }, [progress, translateY, opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: translateY.value }],
    opacity: opacity.value,
  }));

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
      }}
    >
      <Spinner size="sm" color="default" />
      <Animated.View style={animatedStyle}>
        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#71717a",
            fontWeight: "500",
          }}
          numberOfLines={1}
        >
          {progress ?? "Thinking..."}
        </Text>
      </Animated.View>
    </View>
  );
}
