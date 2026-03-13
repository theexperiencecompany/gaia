import * as Haptics from "expo-haptics";

export const haptics = {
  light: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light),
  medium: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium),
  heavy: () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy),
  success: () =>
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success),
  error: () =>
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error),
  warning: () =>
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning),
  selection: () => Haptics.selectionAsync(),
};

export function selectionHaptic(): void {
  void Haptics.selectionAsync();
}

export function impactHaptic(style: "light" | "medium" | "heavy"): void {
  const styleMap = {
    light: Haptics.ImpactFeedbackStyle.Light,
    medium: Haptics.ImpactFeedbackStyle.Medium,
    heavy: Haptics.ImpactFeedbackStyle.Heavy,
  };
  void Haptics.impactAsync(styleMap[style]);
}

export function notificationHaptic(
  type: "success" | "warning" | "error",
): void {
  const typeMap = {
    success: Haptics.NotificationFeedbackType.Success,
    warning: Haptics.NotificationFeedbackType.Warning,
    error: Haptics.NotificationFeedbackType.Error,
  };
  void Haptics.notificationAsync(typeMap[type]);
}

export function longPressHaptic(): void {
  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
}
