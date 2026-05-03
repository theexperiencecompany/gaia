import { Avatar, Spinner } from "heroui-native";
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

export function LoadingIndicator({
  progress,
  toolCategory,
  toolIconUrl,
}: LoadingIndicatorProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const avatarSize = moderateScale(24, 0.5);

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
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.xs,
          paddingTop: 2,
        }}
      >
        <Spinner size="sm" color="default" />

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

        {toolIconElement ? toolIconElement : null}
      </View>
    </View>
  );
}
