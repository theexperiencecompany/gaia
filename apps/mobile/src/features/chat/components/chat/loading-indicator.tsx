import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface LoadingIndicatorProps {
  progress?: string;
}

function PulseDot({ delayMs }: { delayMs: number }) {
  const opacity = useSharedValue(0.3);
  useEffect(() => {
    opacity.value = withDelay(
      delayMs,
      withRepeat(
        withSequence(
          withTiming(1, { duration: 400 }),
          withTiming(0.3, { duration: 400 }),
        ),
        -1,
        false,
      ),
    );
  }, [opacity, delayMs]);
  const style = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));
  return (
    <Animated.View
      style={[
        style,
        {
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: "#a1a1aa",
          marginLeft: delayMs > 0 ? 4 : 0,
        },
      ]}
    />
  );
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
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <PulseDot delayMs={0} />
        <PulseDot delayMs={150} />
        <PulseDot delayMs={300} />
      </View>
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
