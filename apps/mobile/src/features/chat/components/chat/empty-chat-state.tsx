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
        // Nudge the visual centre up slightly to compensate for the
        // header (≈52px) sitting above and the composer (≈60px + safe area)
        // below — without this, content reads as too low on the screen.
        paddingBottom: spacing.xl,
      }}
    >
      <Animated.View
        entering={FadeIn.duration(400)}
        style={{ alignItems: "center" }}
      >
        <Image
          source={GaiaLogo}
          style={{
            width: 56,
            height: 56,
            marginBottom: spacing.md,
          }}
          contentFit="contain"
        />

        <Text
          style={{
            fontSize: 28,
            fontWeight: "600",
            color: "#ffffff",
            textAlign: "center",
            letterSpacing: -0.4,
            lineHeight: 36,
          }}
        >
          {greeting}
        </Text>

        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#71717a",
            textAlign: "center",
            marginTop: spacing.xs,
          }}
        >
          What can I help with?
        </Text>
      </Animated.View>
    </View>
  );
}
