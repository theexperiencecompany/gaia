import { Surface } from "heroui-native";
import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface StreamProgressBarProps {
  progress: number;
  label?: string;
  showLabel?: boolean;
}

export function StreamProgressBar({
  progress,
  label,
  showLabel = true,
}: StreamProgressBarProps) {
  const { spacing, fontSize } = useResponsive();
  const clampedProgress = Math.min(Math.max(progress, 0), 100);
  const width = useSharedValue(0);

  useEffect(() => {
    width.value = withTiming(clampedProgress, { duration: 400 });
  }, [clampedProgress, width]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${width.value}%` as `${number}%`,
  }));

  return (
    <Surface style={{ gap: spacing.xs }}>
      {showLabel && (label || clampedProgress > 0) && (
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          {label ? (
            <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
              {label}
            </Text>
          ) : (
            <View />
          )}
          <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
            {Math.round(clampedProgress)}%
          </Text>
        </View>
      )}

      <View
        style={{
          height: 3,
          backgroundColor: "rgba(255,255,255,0.08)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <Animated.View
          style={[
            barStyle,
            {
              height: "100%",
              backgroundColor: "#00bbff",
              borderRadius: 2,
            },
          ]}
        />
      </View>
    </Surface>
  );
}
