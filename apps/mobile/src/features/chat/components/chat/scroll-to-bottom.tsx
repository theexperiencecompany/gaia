import { PressableFeedback } from "heroui-native";
import { useEffect, useRef } from "react";
import { Animated } from "react-native";
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
  const opacity = useRef(new Animated.Value(0)).current;
  const { moderateScale, iconSize } = useResponsive();
  const buttonSize = moderateScale(36, 0.5);

  useEffect(() => {
    Animated.timing(opacity, {
      toValue: visible ? 1 : 0,
      duration: 200,
      useNativeDriver: true,
    }).start();
  }, [visible, opacity]);

  return (
    <Animated.View
      pointerEvents={visible ? "auto" : "none"}
      style={{
        position: "absolute",
        bottom: moderateScale(12, 0.5),
        right: moderateScale(16, 0.5),
        zIndex: 10,
        opacity,
      }}
    >
      <PressableFeedback
        onPress={onPress}
        style={{
          width: buttonSize,
          height: buttonSize,
          borderRadius: buttonSize / 2,
          backgroundColor: "rgba(30, 30, 32, 0.9)",
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.1)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon
          icon={ArrowDown02Icon}
          size={iconSize.md}
          color="rgba(255,255,255,0.6)"
        />
      </PressableFeedback>
    </Animated.View>
  );
}
