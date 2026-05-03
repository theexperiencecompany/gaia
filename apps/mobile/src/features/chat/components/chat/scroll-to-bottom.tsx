import { PressableFeedback } from "heroui-native";
import { useEffect } from "react";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import { AppIcon, ArrowDown02Icon } from "@/components/icons";
import { useResponsive } from "@/lib/responsive";

interface ScrollToBottomButtonProps {
  visible: boolean;
  onPress: () => void;
}

export function ScrollToBottomButton({
  visible,
  onPress,
}: ScrollToBottomButtonProps) {
  const { spacing, iconSize, moderateScale } = useResponsive();
  const buttonSize = 40;

  const opacity = useSharedValue(0);
  const translateY = useSharedValue(12);

  useEffect(() => {
    opacity.value = withSpring(visible ? 1 : 0, {
      damping: 18,
      stiffness: 280,
    });
    translateY.value = withSpring(visible ? 0 : 12, {
      damping: 18,
      stiffness: 280,
    });
  }, [visible, opacity, translateY]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ translateY: translateY.value }],
  }));

  return (
    <Animated.View
      pointerEvents={visible ? "auto" : "none"}
      style={[
        {
          position: "absolute",
          bottom: spacing.lg,
          right: moderateScale(16, 0.5),
          zIndex: 10,
          shadowColor: "#000000",
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.4,
          shadowRadius: 8,
          elevation: 8,
        },
        animatedStyle,
      ]}
    >
      <PressableFeedback
        onPress={onPress}
        style={{
          width: buttonSize,
          height: buttonSize,
          borderRadius: buttonSize / 2,
          backgroundColor: "rgba(39, 39, 42, 0.95)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon
          icon={ArrowDown02Icon}
          size={iconSize.md}
          color="rgba(255,255,255,0.85)"
        />
      </PressableFeedback>
    </Animated.View>
  );
}
