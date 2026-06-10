import { useRouter } from "expo-router";
import { Pressable } from "react-native";
import { AppIcon, ArrowLeft01Icon } from "@/components/icons";

export interface BackButtonProps {
  /**
   * Override the default `router.back()` behavior. Useful when a screen has
   * an internal sub-state (e.g. integrations community sub-view) and the
   * back button should pop the sub-state before falling through to nav.
   */
  onPress?: () => void;
  /**
   * Hide the button entirely when `router.canGoBack()` is false. Default: true.
   */
  hideWhenCannotGoBack?: boolean;
  accessibilityLabel?: string;
}

/**
 * Standard back button used across every mobile screen header.
 * Solid 40×40 round with always-on subtle bg so it reads as a button at rest.
 */
export function BackButton({
  onPress,
  hideWhenCannotGoBack = true,
  accessibilityLabel = "Go back",
}: BackButtonProps) {
  const router = useRouter();
  const canGoBack = router.canGoBack();

  if (!onPress && hideWhenCannotGoBack && !canGoBack) {
    return null;
  }

  const handlePress = () => {
    if (onPress) {
      onPress();
      return;
    }
    if (canGoBack) router.back();
  };

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => ({
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: pressed
          ? "rgba(255,255,255,0.12)"
          : "rgba(255,255,255,0.06)",
      })}
    >
      <AppIcon icon={ArrowLeft01Icon} size={20} color="#ffffff" />
    </Pressable>
  );
}
