import { DarkTheme, DefaultTheme, type Theme } from "@react-navigation/native";

/**
 * Theme tokens for the mobile app.
 *
 * Dark mode uses a custom palette optimized for mobile (iOS system colors):
 *   background:       #131416  (main bg)
 *   surface:          #171920  (card / sheet bg)
 *   foreground:       #ffffff
 *   muted:            #2d2d2d  (separator / subtle bg)
 *   muted-foreground: #8e8e93  (secondary text, iOS system gray)
 *   primary:          #00bbff  (brand)
 *   success:          #34c759  (iOS green)
 *   warning:          #ff9500  (iOS orange)
 *   danger/error:     #ff3b30  (iOS red)
 *   border:           rgba(255,255,255,0.1)
 */
export const THEME = {
  light: {
    background: "#ffffff",
    foreground: "#111827",
    card: "#ffffff",
    cardForeground: "#111827",
    popover: "#ffffff",
    popoverForeground: "#111827",
    primary: "#00bbff",
    primaryForeground: "#000000",
    secondary: "#f3f4f6",
    secondaryForeground: "#111827",
    muted: "#f3f4f6",
    mutedForeground: "#6b7280",
    accent: "#00bbff",
    accentForeground: "#000000",
    destructive: "#ff3b30",
    border: "rgba(0,0,0,0.1)",
    input: "#e5e7eb",
    ring: "#00bbff",
    success: "#34c759",
    successForeground: "#000000",
    warning: "#ff9500",
    warningForeground: "#000000",
    radius: "0.5rem",
  },
  dark: {
    background: "#131416",
    foreground: "#ffffff",
    card: "#171920",
    cardForeground: "#ffffff",
    popover: "#171920",
    popoverForeground: "#ffffff",
    primary: "#00bbff",
    primaryForeground: "#000000",
    secondary: "#1c1c1e",
    secondaryForeground: "#ffffff",
    muted: "#2d2d2d",
    mutedForeground: "#8e8e93",
    accent: "#00bbff",
    accentForeground: "#000000",
    destructive: "#ff3b30",
    border: "rgba(255,255,255,0.1)",
    input: "#2d2d2d",
    ring: "#00bbff",
    success: "#34c759",
    successForeground: "#000000",
    warning: "#ff9500",
    warningForeground: "#000000",
    radius: "0.5rem",
  },
};

export const NAV_THEME: Record<"light" | "dark", Theme> = {
  light: {
    ...DefaultTheme,
    colors: {
      background: THEME.light.background,
      border: THEME.light.border,
      card: THEME.light.card,
      notification: THEME.light.destructive,
      primary: THEME.light.primary,
      text: THEME.light.foreground,
    },
  },
  dark: {
    ...DarkTheme,
    colors: {
      background: THEME.dark.background,
      border: THEME.dark.border,
      card: THEME.dark.card,
      notification: THEME.dark.destructive,
      primary: THEME.dark.primary,
      text: THEME.dark.foreground,
    },
  },
};

export const Colors = {
  light: {
    text: THEME.light.foreground,
    background: THEME.light.background,
    tint: THEME.light.primary,
    icon: THEME.light.mutedForeground,
    tabIconDefault: THEME.light.mutedForeground,
    tabIconSelected: THEME.light.primary,
  },
  dark: {
    text: THEME.dark.foreground,
    background: THEME.dark.background,
    tint: THEME.dark.primary,
    icon: THEME.dark.mutedForeground,
    tabIconDefault: THEME.dark.mutedForeground,
    tabIconSelected: THEME.dark.primary,
  },
};
