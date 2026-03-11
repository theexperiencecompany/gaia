import { useColorScheme } from "react-native";
import { useThemeStore } from "@/lib/theme-store";

/**
 * Returns the resolved active theme ('light' | 'dark') based on:
 * - The user's stored preference (ThemeStore)
 * - The system color scheme when mode is 'system'
 */
export function useAppTheme(): "light" | "dark" {
  const mode = useThemeStore((s) => s.mode);
  const systemScheme = useColorScheme();

  if (mode === "system") {
    const resolved = systemScheme ?? "dark";
    return resolved as "light" | "dark";
  }

  return mode as "light" | "dark";
}
