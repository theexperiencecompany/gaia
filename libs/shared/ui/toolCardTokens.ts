/**
 * Shared ToolCard tokens — single source of truth for OpenUI ToolCard layout.
 *
 * Source: apps/web/src/config/openui/primitives/ToolCard.tsx
 * This module extracts the visual constants so web, mobile, and shared
 * renderers stay in sync. Consumers should import SIZE_MAX_W / padding / gap
 * from here instead of hard-coding Tailwind strings.
 */

export type ToolCardSize = "compact" | "standard" | "wide" | "full";

/**
 * Max-width per card size. Mirrors the private `SIZE_MAX_W` map in ToolCard.tsx.
 * Tailwind classes; empty string means no max-width (full).
 */
export const SIZE_MAX_W: Record<ToolCardSize, string> = {
  compact: "max-w-md",
  standard: "max-w-2xl",
  wide: "max-w-4xl",
  full: "",
} as const;

/**
 * Numeric max-widths (px) for non-Tailwind consumers (React Native, canvas, PDF).
 * Derived from Tailwind's scale: md=448, 2xl=672, 4xl=896.
 */
export const SIZE_MAX_W_PX: Record<ToolCardSize, number | null> = {
  compact: 448,
  standard: 672,
  wide: 896,
  full: null,
} as const;

// ---------------------------------------------------------------------------
// Layout tokens — extracted from ToolCard JSX
// ---------------------------------------------------------------------------

/** Outer container: "rounded-2xl bg-zinc-800 p-4 w-full" */
export const TOOL_CARD_OUTER = "rounded-2xl bg-zinc-800 p-4 w-full" as const;
export const TOOL_CARD_BG = "bg-zinc-800" as const;
export const TOOL_CARD_ROUNDED = "rounded-2xl" as const;
export const TOOL_CARD_PADDING = "p-4" as const;
export const TOOL_CARD_WIDTH = "w-full" as const;

/** Header wrapper: "mb-3" */
export const TOOL_CARD_HEADER_GAP = "mb-3" as const;
export const TOOL_CARD_HEADER_TITLE =
  "text-sm font-semibold text-zinc-100" as const;
export const TOOL_CARD_HEADER_SUBTITLE =
  "text-xs text-zinc-400 mt-0.5" as const;

/** Children stack: "flex flex-col gap-3" */
export const TOOL_CARD_GAP = "gap-3" as const;
export const TOOL_CARD_STACK = "flex flex-col gap-3" as const;

/** Footer wrapper: "mt-3" */
export const TOOL_CARD_FOOTER_GAP = "mt-3" as const;

/**
 * Single token object for spread / theme providers.
 */
export const toolCardTokens = {
  SIZE_MAX_W,
  SIZE_MAX_W_PX,
  outer: TOOL_CARD_OUTER,
  bg: TOOL_CARD_BG,
  rounded: TOOL_CARD_ROUNDED,
  padding: TOOL_CARD_PADDING,
  width: TOOL_CARD_WIDTH,
  headerGap: TOOL_CARD_HEADER_GAP,
  headerTitle: TOOL_CARD_HEADER_TITLE,
  headerSubtitle: TOOL_CARD_HEADER_SUBTITLE,
  gap: TOOL_CARD_GAP,
  stack: TOOL_CARD_STACK,
  footerGap: TOOL_CARD_FOOTER_GAP,
} as const;

export type ToolCardTokens = typeof toolCardTokens;
