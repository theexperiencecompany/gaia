import { useEffect } from "react";
import { View } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";

/**
 * Blinking caret shown at the end of the last bubble while a response streams
 * — the mobile counterpart of web's streaming cursor treatment.
 */
export function StreamingCursor({ color = "#e4e4e7" }: { color?: string }) {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.15, { duration: 450 }),
        withTiming(1, { duration: 450 }),
      ),
      -1,
      true,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Reanimated.View style={animatedStyle}>
      <View
        style={{
          width: 3,
          height: 16,
          borderRadius: 2,
          backgroundColor: color,
          marginTop: 2,
        }}
      />
    </Reanimated.View>
  );
}
