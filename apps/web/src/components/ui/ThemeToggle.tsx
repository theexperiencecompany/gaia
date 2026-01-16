"use client";

import { type Theme, useTheme } from "@/components/providers/ThemeProvider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { ComputerIcon, MoonIcon, Sun03Icon as SunIcon } from "../shared/icons";

interface ThemeToggleProps {
  variant?: "icon" | "dropdown";
  className?: string;
}

export function ThemeToggle({
  variant = "dropdown",
  className,
}: ThemeToggleProps) {
  const { theme, setTheme, resolvedTheme } = useTheme();

  if (variant === "icon") {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        className={cn("size-9", className)}
        aria-label={`Switch to ${resolvedTheme === "dark" ? "light" : "dark"} mode`}
      >
        {resolvedTheme === "dark" ? (
          <SunIcon className="size-5" />
        ) : (
          <MoonIcon className="size-5" />
        )}
      </Button>
    );
  }

  const themeOptions: { value: Theme; label: string; icon: React.ReactNode }[] =
    [
      { value: "light", label: "Light", icon: <SunIcon className="size-4" /> },
      { value: "dark", label: "Dark", icon: <MoonIcon className="size-4" /> },
      {
        value: "system",
        label: "System",
        icon: <ComputerIcon className="size-4" />,
      },
    ];

  const currentIcon =
    theme === "system" ? (
      <ComputerIcon className="size-5" />
    ) : resolvedTheme === "dark" ? (
      <MoonIcon className="size-5" />
    ) : (
      <SunIcon className="size-5" />
    );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("size-9", className)}
          aria-label="Toggle theme"
        >
          {currentIcon}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {themeOptions.map((option) => (
          <DropdownMenuItem
            key={option.value}
            onClick={() => setTheme(option.value)}
            className={cn(
              "flex items-center gap-2 cursor-pointer",
              theme === option.value && "bg-accent",
            )}
          >
            {option.icon}
            <span>{option.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
