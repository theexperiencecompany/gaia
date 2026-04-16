import { getCompleteTimeBasedGreeting } from "@gaia/shared/utils";
import { Image } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";
import Animated, { FadeInUp } from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/logo.svg");

interface EmptyChatStateProps {
  onSuggestionPress: (prompt: string) => void;
}

export function EmptyChatState({ onSuggestionPress: _ }: EmptyChatStateProps) {
  const { user } = useAuth();
  const { spacing, fontSize, moderateScale } = useResponsive();

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
        paddingBottom: spacing.xl,
      }}
    >
      <Animated.View
        entering={FadeInUp.delay(0).springify()}
        style={{ alignItems: "center" }}
      >
        <View
          style={{
            width: moderateScale(72, 0.5),
            height: moderateScale(72, 0.5),
            borderRadius: moderateScale(18, 0.5),
            overflow: "hidden",
            marginBottom: spacing.lg,
          }}
        >
          <Image
            source={GaiaLogo}
            style={{ width: "100%", height: "100%" }}
            contentFit="contain"
          />
        </View>

        <Text
          style={{
            fontSize: moderateScale(28, 0.4),
            fontWeight: "600",
            color: "#ffffff",
            textAlign: "center",
            letterSpacing: -0.5,
            marginBottom: spacing.xs,
            lineHeight: moderateScale(36, 0.4),
          }}
        >
          {greeting}
        </Text>

        <Text
          style={{
            fontSize: fontSize.base,
            color: "#71717a",
            textAlign: "center",
            fontWeight: "400",
          }}
        >
          Ask me anything...
        </Text>
      </Animated.View>
    </View>
  );
}
