import type { ReactNode } from "react";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { type AnyIcon, AppIcon, ArrowDown02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

interface CollapsibleCardProps {
  /** Leading icon in the header row (AppIcon variant) */
  icon?: AnyIcon;
  /** Leading icon as a custom ReactNode (e.g. inline SVG) — takes precedence over icon */
  customIcon?: ReactNode;
  iconColor?: string;
  iconSize?: number;
  /** Header title. String, or function that receives current open state. */
  title: string | ((open: boolean) => string);
  /** Optional node rendered between title and chevron (e.g. a pill) */
  trailing?: ReactNode;
  /** Start expanded (default true) */
  defaultOpen?: boolean;
  /** Collapsible body */
  children: ReactNode;
  /** Outer radius, matches web per-card choice */
  radius?: "2xl" | "3xl";
  /** Header title color intensity. "muted" = zinc-400 (inbox), "bright" = zinc-200 (thread) */
  titleTone?: "muted" | "bright";
}

export function CollapsibleCard({
  icon,
  customIcon,
  iconColor = "#a1a1aa",
  iconSize = 20,
  title,
  trailing,
  defaultOpen = true,
  children,
  radius = "2xl",
  titleTone = "bright",
}: CollapsibleCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const radiusClass = radius === "3xl" ? "rounded-3xl" : "rounded-2xl";
  const titleClass =
    titleTone === "muted"
      ? "text-zinc-400 text-sm"
      : "text-zinc-200 text-sm font-medium";

  return (
    <View className={`mx-4 my-1 ${radiusClass} bg-zinc-800 px-3`}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        className="flex-row items-center gap-2 py-3"
        hitSlop={8}
      >
        {customIcon ??
          (icon && <AppIcon icon={icon} size={iconSize} color={iconColor} />)}
        <Text className={`flex-1 ${titleClass}`} numberOfLines={1}>
          {typeof title === "function" ? title(open) : title}
        </Text>
        {trailing}
        <View
          style={{
            transform: [{ rotate: open ? "0deg" : "-90deg" }],
          }}
        >
          <AppIcon icon={ArrowDown02Icon} size={14} color="#a1a1aa" />
        </View>
      </Pressable>
      {open && <View className="pb-3">{children}</View>}
    </View>
  );
}
