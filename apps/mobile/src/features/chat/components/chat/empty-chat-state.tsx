import { Image } from "expo-image";
import { PressableFeedback } from "heroui-native";
import { useMemo } from "react";
import { ScrollView, View } from "react-native";
import Animated, { FadeInDown, FadeInUp } from "react-native-reanimated";
import type { AnyIcon } from "@/components/icons";
import {
  Analytics01Icon,
  AppIcon,
  Brain02Icon,
  Calendar03Icon,
  CheckListIcon,
  Mail01Icon,
  PencilEdit01Icon,
  Search01Icon,
  SourceCodeCircleIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";
import { SUGGESTION_CHIPS } from "../../data/suggestions";

const iconMap: Record<string, AnyIcon> = {
  Mail01Icon,
  Calendar03Icon,
  CheckListIcon,
  Search01Icon,
  SourceCodeCircleIcon,
  PencilEdit01Icon,
  Brain02Icon,
  Analytics01Icon,
};

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

interface SuggestionChipProps {
  icon: string;
  label: string;
  accentColor: string;
  onPress: () => void;
  index: number;
}

function SuggestionChipItem({
  icon,
  label,
  accentColor,
  onPress,
  index,
}: SuggestionChipProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const iconComponent = iconMap[icon];

  return (
    <Animated.View entering={FadeInDown.delay(300 + index * 60).springify()}>
      <PressableFeedback
        onPress={onPress}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.xs,
          backgroundColor: "rgba(255,255,255,0.04)",
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.08)",
          borderRadius: moderateScale(20, 0.5),
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
        }}
      >
        {iconComponent && (
          <View
            style={{
              width: moderateScale(22, 0.5),
              height: moderateScale(22, 0.5),
              borderRadius: moderateScale(11, 0.5),
              backgroundColor: `${accentColor}18`,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon
              icon={iconComponent}
              size={moderateScale(12, 0.5)}
              color={accentColor}
            />
          </View>
        )}
        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#d4d4d8",
            fontWeight: "500",
          }}
          numberOfLines={1}
        >
          {label}
        </Text>
      </PressableFeedback>
    </Animated.View>
  );
}

interface EmptyChatStateProps {
  onSuggestionPress: (prompt: string) => void;
}

export function EmptyChatState({ onSuggestionPress }: EmptyChatStateProps) {
  const { user } = useAuth();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const greeting = useMemo(() => getGreeting(user?.name), [user?.name]);

  // Split chips into two rows for a staggered grid look
  const row1 = SUGGESTION_CHIPS.slice(0, 4);
  const row2 = SUGGESTION_CHIPS.slice(4, 8);

  return (
    <ScrollView
      contentContainerStyle={{
        flexGrow: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.lg,
        paddingBottom: spacing.xl,
      }}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      {/* Logo + Greeting */}
      <Animated.View
        entering={FadeInUp.delay(0).springify()}
        style={{ alignItems: "center", marginBottom: spacing.xl + 4 }}
      >
        <View
          style={{
            width: moderateScale(56, 0.5),
            height: moderateScale(56, 0.5),
            borderRadius: moderateScale(16, 0.5),
            overflow: "hidden",
            marginBottom: spacing.lg,
            backgroundColor: "rgba(255,255,255,0.05)",
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
          }}
        >
          <Image
            source={require("../../../../../assets/images/icon.png")}
            style={{ width: "100%", height: "100%" }}
            contentFit="cover"
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

      {/* Suggestion chips - row 1 */}
      <Animated.View
        entering={FadeInDown.delay(200).springify()}
        style={{ width: "100%", marginBottom: spacing.sm }}
      >
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: spacing.sm, paddingHorizontal: 2 }}
        >
          {row1.map((chip, index) => (
            <SuggestionChipItem
              key={chip.id}
              icon={chip.icon}
              label={chip.label}
              accentColor={chip.accentColor}
              onPress={() => onSuggestionPress(chip.prompt)}
              index={index}
            />
          ))}
        </ScrollView>
      </Animated.View>

      {/* Suggestion chips - row 2 */}
      <Animated.View
        entering={FadeInDown.delay(250).springify()}
        style={{ width: "100%" }}
      >
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: spacing.sm, paddingHorizontal: 2 }}
        >
          {row2.map((chip, index) => (
            <SuggestionChipItem
              key={chip.id}
              icon={chip.icon}
              label={chip.label}
              accentColor={chip.accentColor}
              onPress={() => onSuggestionPress(chip.prompt)}
              index={index + 4}
            />
          ))}
        </ScrollView>
      </Animated.View>
    </ScrollView>
  );
}
