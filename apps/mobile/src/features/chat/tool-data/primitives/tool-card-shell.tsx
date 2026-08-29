import {
  SIZE_MAX_W,
  SIZE_MAX_W_PX,
  type ToolCardSize,
  toolCardTokens,
} from "@gaia/shared/ui";
import type { ReactNode } from "react";
import { View, type ViewStyle } from "react-native";

/**
 * Mobile ToolCard shell — parity with web `apps/web/src/config/openui/primitives/ToolCard.tsx`.
 *
 * Uses shared `toolCardTokens` + `SIZE_MAX_W` so web/mobile stay in sync on:
 *   - outer bg/padding/rounded (rounded-2xl bg-zinc-800 p-4 w-full)
 *   - header/body gaps, typography classes
 *   - per-size max-width (compact/standard/wide/full)
 *
 * Mobile adds `mx-4 my-1` for RN list inset (web centers via parent max-w).
 * For native layout the numeric `maxWidth` is applied via `style` (RN ignores Tailwind max-w class on native),
 * while the Tailwind class is kept for `expo start --web` parity.
 *
 * @see libs/shared/ts/src/ui/toolCardTokens.ts
 * @see apps/web/src/config/openui/primitives/ToolCard.tsx
 */
interface ToolCardShellProps {
  children: ReactNode;
  className?: string;
  size?: ToolCardSize;
  style?: ViewStyle;
}

export type { ToolCardSize };

export function ToolCardShell({
  children,
  className,
  size = "standard",
  style,
}: ToolCardShellProps) {
  const maxWidth = SIZE_MAX_W_PX[size];

  // RN: numeric maxWidth for native; Tailwind max-w class for web
  const maxWidthStyle: ViewStyle | undefined =
    maxWidth != null ? { maxWidth } : undefined;

  return (
    <View
      style={[maxWidthStyle as ViewStyle, style]}
      className={`${toolCardTokens.outer} mx-4 my-1 ${SIZE_MAX_W[size]} ${className ?? ""}`.trim()}
    >
      {children}
    </View>
  );
}
