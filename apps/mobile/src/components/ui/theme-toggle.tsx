import { colorScheme } from "nativewind";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import {
  HugeiconsIcon,
  Moon02Icon,
  Settings01Icon,
  Sun01Icon,
} from "@/components/icons";
import { cn } from "@/lib/utils";
import { Text } from "./text";

type ThemeOption = "light" | "dark" | "system";

interface ThemeToggleProps {
  className?: string;
  showLabel?: boolean;
}

export function ThemeToggle({
  className,
  showLabel = false,
}: ThemeToggleProps) {
  const [selectedTheme, setSelectedTheme] = useState<ThemeOption>("system");

  const setTheme = (theme: ThemeOption) => {
    setSelectedTheme(theme);
    colorScheme.set(theme);
  };

  const themes: Array<{
    value: ThemeOption;
    icon: typeof Sun01Icon;
    label: string;
  }> = [
    { value: "light", icon: Sun01Icon, label: "Light" },
    { value: "dark", icon: Moon02Icon, label: "Dark" },
    { value: "system", icon: Settings01Icon, label: "System" },
  ];

  return (
    <View className={cn("flex-row items-center gap-2", className)}>
      {themes.map((theme) => {
        const isActive = selectedTheme === theme.value;
        return (
          <Pressable
            key={theme.value}
            onPress={() => setTheme(theme.value)}
            className={cn(
              "flex-row items-center gap-2 px-3 py-2 rounded-lg",
              "active:opacity-70 transition-all",
              isActive
                ? "bg-primary dark:bg-primary"
                : "bg-secondary dark:bg-secondary",
            )}
          >
            <HugeiconsIcon
              icon={theme.icon}
              size={18}
              color={
                isActive
                  ? "hsl(var(--primary-foreground))"
                  : "hsl(var(--foreground))"
              }
              strokeWidth={1.5}
            />
            {showLabel && (
              <Text
                className={cn(
                  "text-sm font-medium",
                  isActive ? "text-primary-foreground" : "text-foreground",
                )}
              >
                {theme.label}
              </Text>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

export function ThemeToggleButton({ className }: { className?: string }) {
  const [selectedTheme, setSelectedTheme] = useState<ThemeOption>("system");

  useEffect(() => {
    const stored = colorScheme.get();
    if (stored) {
      setSelectedTheme(stored as ThemeOption);
    }
  }, []);

  const toggleTheme = () => {
    const themes: ThemeOption[] = ["light", "dark", "system"];
    const currentIndex = themes.indexOf(selectedTheme);
    const nextIndex = (currentIndex + 1) % themes.length;
    const newTheme = themes[nextIndex];
    setSelectedTheme(newTheme);
    colorScheme.set(newTheme);
  };

  const getIcon = () => {
    switch (selectedTheme) {
      case "light":
        return Sun01Icon;
      case "dark":
        return Moon02Icon;
      default:
        return Settings01Icon;
    }
  };

  return (
    <Pressable
      onPress={toggleTheme}
      className={cn(
        "w-10 h-10 items-center justify-center rounded-lg",
        "bg-secondary dark:bg-secondary active:opacity-70",
        className,
      )}
    >
      <HugeiconsIcon
        icon={getIcon()}
        size={20}
        color="hsl(var(--foreground))"
        strokeWidth={1.5}
      />
    </Pressable>
  );
}
