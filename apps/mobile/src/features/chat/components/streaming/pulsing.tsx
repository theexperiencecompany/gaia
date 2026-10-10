import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  cancelAnimation,
  type SharedValue,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";

/**
 * The ONE pulsing animation primitive for chat streaming surfaces.
 * ThinkingCard / ToolProgressCard / ThinkingBubble each used to carry their
 * own copy of this loop — they all route through here now.
 */

const PULSE_MIN_OPACITY = 0.3;
const PULSE_HALF_PERIOD_MS = 450;

/** Repeating opacity loop shared by every pulse consumer. */
function usePulseOpacity(delayMs = 0): Readonly<SharedValue<number>> {
  const opacity = useSharedValue(PULSE_MIN_OPACITY);

  useEffect(() => {
    opacity.value = withDelay(
      delayMs,
      withRepeat(
        withSequence(
          withTiming(1, { duration: PULSE_HALF_PERIOD_MS }),
          withTiming(PULSE_MIN_OPACITY, { duration: PULSE_HALF_PERIOD_MS }),
        ),
        -1,
        false,
      ),
    );
    return () => cancelAnimation(opacity);
  }, [opacity, delayMs]);

  return opacity;
}

/** Solid circular dot whose opacity pulses — the canonical "working" marker. */
export function PulsingDot({
  size,
  color,
  delayMs = 0,
}: {
  size: number;
  color: string;
  delayMs?: number;
}) {
  const opacity = usePulseOpacity(delayMs);
  const style = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[
        style,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: color,
        },
      ]}
    />
  );
}

/** Wraps arbitrary children (usually an icon) in the same pulse loop. */
export function Pulsing({
  children,
  delayMs = 0,
}: {
  children: React.ReactNode;
  delayMs?: number;
}) {
  const opacity = usePulseOpacity(delayMs);
  const style = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <View accessible={false}>
      <Animated.View style={style}>{children}</Animated.View>
    </View>
  );
}
