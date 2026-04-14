import { Image } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";
import Animated, { FadeInUp } from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/gaia.png");

function getGreeting(name?: string): string {
  const hour = new Date().getHours();
  let base: string;
  if (hour >= 5 && hour < 12) {
    base = "Good morning";
  } else if (hour >= 12 && hour < 17) {
    base = "Good afternoon";
  } else if (hour >= 17 && hour < 21) {
    base = "Good evening";
  } else {
    base = "Good night";
  }
  if (name?.trim()) {
    const firstName = name.trim().split(" ")[0];
    return `${base}, ${firstName}`;
  }
  return base;
}

interface EmptyChatStateProps {
  onSuggestionPress: (prompt: string) => void;
}

export function EmptyChatState({ onSuggestionPress: _ }: EmptyChatStateProps) {
  const { user } = useAuth();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const greeting = useMemo(() => getGreeting(user?.name), [user?.name]);

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.lg,
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
