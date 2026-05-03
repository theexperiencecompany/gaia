import { Spinner } from "heroui-native";
import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface LoadingIndicatorProps {
  progress?: string;
}

export function LoadingIndicator({ progress }: LoadingIndicatorProps) {
  const { spacing, fontSize } = useResponsive();

  // Slide-up text animation on progress change
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
      <Spinner size="sm" color="default" />
      <Animated.View
        style={{
          transform: [{ translateY: textTranslateY }],
          opacity: textOpacity,
        }}
      >
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
