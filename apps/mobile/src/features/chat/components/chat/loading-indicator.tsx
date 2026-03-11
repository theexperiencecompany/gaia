import { Avatar } from "heroui-native";
import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/gaia.png");

interface LoadingIndicatorProps {
  progress?: string;
}

function AnimatedDots() {
  const { moderateScale } = useResponsive();
  const dotSize = moderateScale(6, 0.5);

  const dot1 = useRef(new Animated.Value(0.3)).current;
  const dot2 = useRef(new Animated.Value(0.3)).current;
  const dot3 = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    const makeDotAnim = (dot: Animated.Value, delay: number) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(delay),
          Animated.timing(dot, {
            toValue: 1,
            duration: 400,
            useNativeDriver: true,
          }),
          Animated.timing(dot, {
            toValue: 0.3,
            duration: 400,
            useNativeDriver: true,
          }),
        ]),
      );

    const a1 = makeDotAnim(dot1, 0);
    const a2 = makeDotAnim(dot2, 150);
    const a3 = makeDotAnim(dot3, 300);

    a1.start();
    a2.start();
    a3.start();

    return () => {
      dot1.stopAnimation();
      dot2.stopAnimation();
      dot3.stopAnimation();
    };
  }, [dot1, dot2, dot3]);

  const dotStyle = {
    width: dotSize,
    height: dotSize,
    borderRadius: dotSize / 2,
    backgroundColor: "#00bbff",
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: moderateScale(4, 0.5),
      }}
    >
      <Animated.View style={[dotStyle, { opacity: dot1 }]} />
      <Animated.View style={[dotStyle, { opacity: dot2 }]} />
      <Animated.View style={[dotStyle, { opacity: dot3 }]} />
    </View>
  );
}

export function LoadingIndicator({ progress }: LoadingIndicatorProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const avatarSize = moderateScale(24, 0.5);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
      }}
    >
      <Avatar
        alt="Gaia"
        size="sm"
        color="default"
        style={{ width: avatarSize, height: avatarSize }}
      >
        <Avatar.Image source={GaiaLogo} />
        <Avatar.Fallback>G</Avatar.Fallback>
      </Avatar>

      <View
        style={{
          flexDirection: "column",
          gap: spacing.xs,
          paddingTop: 2,
        }}
      >
        {progress ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              fontWeight: "500",
            }}
            numberOfLines={1}
          >
            {progress}
          </Text>
        ) : null}
        <AnimatedDots />
      </View>
    </View>
  );
}
