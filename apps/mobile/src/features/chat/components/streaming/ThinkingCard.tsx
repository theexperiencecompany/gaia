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
import { AppIcon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

function AnimatedDot({ delayMs, size }: { delayMs: number; size: number }) {
  const opacity = useSharedValue(0.3);

  useEffect(() => {
    opacity.value = withDelay(
      delayMs,
      withRepeat(
        withSequence(
          withTiming(1, { duration: 450 }),
          withTiming(0.3, { duration: 450 }),
        ),
        -1,
        false,
      ),
    );
  }, [opacity, delayMs]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        animatedStyle,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: "#a1a1aa",
        },
      ]}
    />
  );
}

interface ThinkingCardProps {
  message?: string;
}

export function ThinkingCard({ message }: ThinkingCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const dotSize = moderateScale(5, 0.5);

  const iconOpacity = useSharedValue(0.6);
  useEffect(() => {
    iconOpacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 600 }),
        withTiming(0.6, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [iconOpacity]);

  const iconStyle = useAnimatedStyle(() => ({ opacity: iconOpacity.value }));

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingVertical: spacing.xs,
      }}
    >
      <Animated.View style={iconStyle}>
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(16, 0.5)}
          color="#a1a1aa"
        />
      </Animated.View>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#71717a",
          fontWeight: "500",
        }}
      >
        {message || "Thinking"}
      </Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <AnimatedDot delayMs={0} size={dotSize} />
        <AnimatedDot delayMs={200} size={dotSize} />
        <AnimatedDot delayMs={400} size={dotSize} />
      </View>
    </View>
  );
}
