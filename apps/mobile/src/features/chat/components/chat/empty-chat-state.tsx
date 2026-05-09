import { getCompleteTimeBasedGreeting } from "@gaia/shared/utils";
import { Image } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";
import Animated, { FadeIn } from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/logo.svg");

export function EmptyChatState() {
  const { user } = useAuth();
  const { spacing, fontSize } = useResponsive();

  const greeting = useMemo(
    () => getCompleteTimeBasedGreeting(user?.name),
    [user?.name],
  );

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.lg,
        // Slight upward nudge: the composer (~100px) occupies more vertical
        // space than the header (~52px), so true center reads as low.
        // paddingBottom shifts the optical centre toward the screen midpoint.
        paddingBottom: spacing.lg,
      }}
    >
      <Animated.View
        entering={FadeIn.duration(200)}
        style={{
          alignItems: "center",
          gap: spacing.md,
        }}
      >
        <Image
          source={GaiaLogo}
          style={{ width: 56, height: 56 }}
          contentFit="contain"
        />
        <Text
          style={{
            fontSize: fontSize["2xl"],
            fontWeight: "500",
            color: "#ffffff",
            letterSpacing: -0.3,
            lineHeight: Math.round(fontSize["2xl"] * 1.2),
            textAlign: "center",
          }}
        >
          {greeting}
        </Text>
      </Animated.View>
    </View>
  );
}
