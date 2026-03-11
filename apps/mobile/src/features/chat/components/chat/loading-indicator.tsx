import { Avatar } from "heroui-native";
import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/gaia.png");

interface LoadingIndicatorProps {
  progress?: string;
  toolCategory?: string;
  toolIconUrl?: string | null;
}

function WaveSpinnerSquare() {
  const { moderateScale } = useResponsive();
  const dotSize = moderateScale(5, 0.5);
  const gap = moderateScale(3, 0.5);

  const delays = [0, 120, 240, 120, 240, 360, 240, 360, 480];
  const scales = useRef(delays.map(() => new Animated.Value(0.6))).current;

  useEffect(() => {
    const animations = scales.map((scale, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(delays[i]),
          Animated.timing(scale, {
            toValue: 1,
            duration: 300,
            useNativeDriver: true,
          }),
          Animated.timing(scale, {
            toValue: 0.5,
            duration: 400,
            useNativeDriver: true,
          }),
        ]),
      ),
    );

    animations.forEach((a) => a.start());
    return () => {
      scales.forEach((s) => s.stopAnimation());
    };
  }, [scales]);

  const dotStyle = {
    width: dotSize,
    height: dotSize,
    borderRadius: dotSize / 2,
    backgroundColor: "#00bbff",
  };

  return (
    <View style={{ flexDirection: "column", gap }}>
      <View style={{ flexDirection: "row", gap }}>
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[0] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[1] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[2] }] }]}
        />
      </View>
      <View style={{ flexDirection: "row", gap }}>
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[3] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[4] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[5] }] }]}
        />
      </View>
      <View style={{ flexDirection: "row", gap }}>
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[6] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[7] }] }]}
        />
        <Animated.View
          style={[dotStyle, { transform: [{ scale: scales[8] }] }]}
        />
      </View>
    </View>
  );
}

export function LoadingIndicator({
  progress,
  toolCategory,
  toolIconUrl,
}: LoadingIndicatorProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const avatarSize = moderateScale(24, 0.5);

  // Spinning GAIA logo animation
  const spinAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const spin = Animated.loop(
      Animated.timing(spinAnim, {
        toValue: 1,
        duration: 2000,
        useNativeDriver: true,
      }),
    );
    spin.start();
    return () => spin.stop();
  }, [spinAnim]);

  const spinInterpolate = spinAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  // Slide-up text animation
  const textTranslateY = useRef(new Animated.Value(8)).current;
  const textOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    textTranslateY.setValue(8);
    textOpacity.setValue(0);
    Animated.parallel([
      Animated.timing(textTranslateY, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }),
      Animated.timing(textOpacity, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }),
    ]).start();
  }, [progress]);

  const toolIconElement = toolCategory
    ? getToolCategoryIcon(
        toolCategory,
        { size: moderateScale(16, 0.5), showBackground: true, pulsating: true },
        toolIconUrl,
      )
    : null;

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
      <Animated.View style={{ transform: [{ rotate: spinInterpolate }] }}>
        <Avatar
          alt="Gaia"
          size="sm"
          color="default"
          style={{ width: avatarSize, height: avatarSize }}
        >
          <Avatar.Image source={GaiaLogo} />
          <Avatar.Fallback>G</Avatar.Fallback>
        </Avatar>
      </Animated.View>

      <View
        style={{
          flexDirection: "column",
          gap: spacing.xs,
          paddingTop: 2,
        }}
      >
        {progress ? (
          <Animated.View
            style={{
              transform: [{ translateY: textTranslateY }],
              opacity: textOpacity,
            }}
          >
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
          </Animated.View>
        ) : null}

        {toolIconElement ? toolIconElement : <WaveSpinnerSquare />}
      </View>
    </View>
  );
}
