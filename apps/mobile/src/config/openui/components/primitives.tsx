import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { type Text as RNText, View } from "react-native";
import { Text } from "@/components/ui/text";

/**
 * Card styling primitives for OpenUI components.
 *
 * Mirrors the web card contract:
 *   outer:  rounded-2xl bg-zinc-800 p-4
 *   inner:  rounded-2xl bg-zinc-900 p-3
 *   header: text-sm font-semibold text-zinc-100 mb-3
 *   body:   text-sm font-medium text-zinc-200
 *   muted:  text-xs text-zinc-400
 *
 * All OpenUI cards render at full width and let the parent constrain horizontal space.
 */

interface CardProps {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className }: CardProps) {
  return (
    <View className={`rounded-2xl bg-zinc-800 p-4 w-full ${className ?? ""}`}>
      {children}
    </View>
  );
}

export function InnerCard({ children, className }: CardProps) {
  return (
    <View className={`rounded-2xl bg-zinc-900 p-3 ${className ?? ""}`}>
      {children}
    </View>
  );
}

interface TextProps
  extends Omit<ComponentPropsWithoutRef<typeof RNText>, "className"> {
  children: ReactNode;
  className?: string;
}

export function SectionTitle({ children, className, ...rest }: TextProps) {
  return (
    <Text
      className={`text-sm font-semibold text-zinc-100 mb-3 ${className ?? ""}`}
      {...rest}
    >
      {children}
    </Text>
  );
}

export function ItemTitle({ children, className, ...rest }: TextProps) {
  return (
    <Text
      className={`text-sm font-medium text-zinc-200 ${className ?? ""}`}
      {...rest}
    >
      {children}
    </Text>
  );
}

export function MutedText({ children, className, ...rest }: TextProps) {
  return (
    <Text className={`text-xs text-zinc-400 ${className ?? ""}`} {...rest}>
      {children}
    </Text>
  );
}

export function SubtleText({ children, className, ...rest }: TextProps) {
  return (
    <Text className={`text-xs text-zinc-500 ${className ?? ""}`} {...rest}>
      {children}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Status / color mappings
// ---------------------------------------------------------------------------

export type StatusKind =
  | "success"
  | "error"
  | "warning"
  | "info"
  | "pending"
  | "danger";

export const STATUS_DOT_COLOR: Record<string, string> = {
  success: "#34d399",
  error: "#f87171",
  danger: "#f87171",
  warning: "#fbbf24",
  info: "#60a5fa",
  pending: "#71717a",
};

export const STATUS_PILL_BG: Record<string, string> = {
  success: "bg-emerald-400/10",
  error: "bg-red-400/10",
  danger: "bg-red-400/10",
  warning: "bg-amber-400/10",
  info: "bg-blue-400/10",
  pending: "bg-zinc-500/10",
  default: "bg-zinc-700/50",
  primary: "bg-[#00bbff]/10",
};

export const STATUS_PILL_TEXT: Record<string, string> = {
  success: "text-emerald-400",
  error: "text-red-400",
  danger: "text-red-400",
  warning: "text-amber-400",
  info: "text-blue-400",
  pending: "text-zinc-400",
  default: "text-zinc-400",
  primary: "text-[#00bbff]",
};

interface StatusPillProps {
  kind?: string;
  children: ReactNode;
}

export function StatusPill({ kind = "default", children }: StatusPillProps) {
  const bg = STATUS_PILL_BG[kind] ?? STATUS_PILL_BG.default;
  const text = STATUS_PILL_TEXT[kind] ?? STATUS_PILL_TEXT.default;
  return (
    <View className={`rounded-full px-2 py-0.5 ${bg}`}>
      <Text className={`text-xs font-medium ${text}`}>{children}</Text>
    </View>
  );
}

interface StatusDotProps {
  kind?: string;
}

export function StatusDot({ kind = "default" }: StatusDotProps) {
  const color = STATUS_DOT_COLOR[kind] ?? "#71717a";
  return (
    <View
      style={{
        width: 10,
        height: 10,
        borderRadius: 5,
        backgroundColor: color,
      }}
    />
  );
}
