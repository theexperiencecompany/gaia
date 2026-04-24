/**
 * Tool card primitives — mirror the web chat tool card styling contract.
 *
 * Styling contract (see apps/web CLAUDE.md + DESIGN.md):
 *   - Outer card:  rounded-2xl bg-zinc-800 p-4
 *   - Inner row:   rounded-2xl bg-zinc-900 p-3
 *   - Header:      icon + title row, mb-3, text-sm text-zinc-100
 *   - NO borders, NO ring, NO outline
 */

import type { ReactNode } from "react";
import { View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";

interface ToolCardShellProps {
  children: ReactNode;
  className?: string;
}

export function ToolCardShell({ children, className }: ToolCardShellProps) {
  return (
    <View
      className={`mx-4 my-2 rounded-2xl bg-zinc-800 p-4 ${className ?? ""}`}
    >
      {children}
    </View>
  );
}

interface ToolCardInnerProps {
  children: ReactNode;
  className?: string;
}

export function ToolCardInner({ children, className }: ToolCardInnerProps) {
  return (
    <View className={`rounded-2xl bg-zinc-900 p-3 ${className ?? ""}`}>
      {children}
    </View>
  );
}

interface ToolCardHeaderProps {
  icon?: AnyIcon;
  iconColor?: string;
  title: string;
  trailing?: ReactNode;
  className?: string;
}

export function ToolCardHeader({
  icon,
  iconColor = "#00bbff",
  title,
  trailing,
  className,
}: ToolCardHeaderProps) {
  return (
    <View
      className={`mb-3 flex-row items-center justify-between ${className ?? ""}`}
    >
      <View className="flex-row items-center gap-2 flex-1">
        {icon ? <AppIcon icon={icon} size={16} color={iconColor} /> : null}
        <Text className="text-sm text-zinc-100" numberOfLines={1}>
          {title}
        </Text>
      </View>
      {trailing ? <View className="ml-2">{trailing}</View> : null}
    </View>
  );
}
