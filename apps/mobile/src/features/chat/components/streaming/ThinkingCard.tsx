import { Card } from "heroui-native";
import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

function AnimatedDot({ delay }: { delay: number }) {
  const opacity = useSharedValue(0.3);
  const { moderateScale } = useResponsive();
  const dotSize = moderateScale(6, 0.5);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.3, { duration: delay }),
        withTiming(1, { duration: 400 }),
        withTiming(0.3, { duration: 400 }),
      ),
      -1,
      false,
    );
  }, [opacity, delay]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        animatedStyle,
        {
          width: dotSize,
          height: dotSize,
          borderRadius: dotSize / 2,
          backgroundColor: "#00bbff",
        },
      ]}
    />
  );
}

export function ThinkingCard() {
  const { spacing, fontSize } = useResponsive();

  return (
    <Card
      variant="secondary"
      animation="disable-all"
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: spacing.sm,
        paddingHorizontal: spacing.md,
        gap: spacing.sm,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#8e8e93",
        }}
      >
        Thinking
      </Text>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
        }}
      >
        <AnimatedDot delay={0} />
        <AnimatedDot delay={150} />
        <AnimatedDot delay={300} />
      </View>
    </Card>
  );
}
