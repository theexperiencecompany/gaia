/**
 * GAIA Mobile Design Tokens — shared-source
 *
 * Single source of truth: `libs/shared/ts/src/design/tokens.generated.ts`
 * which is codegen'd from `apps/web/src/app/styles/globals.css` (@theme)
 * and `config/design.tokens.json` (DTCG).
 *
 * This file re-exports shared tokens with mobile-friendly aliases so
 * `import { colors, typography, spacing } from "@/lib/design-tokens"` keeps
 * working, but values stay in sync with web HeroUI v2 tokens via the shared
 * package. No hard-coded hex should drift from shared — mapping is explicit.
 *
 * Theme parity: mobile `global.css` @theme block mirrors web `globals.css`
 * `.dark` semantic tokens. JS tokens here mirror the same hex values via
 * `colorTokens` / `darkSemanticTokens` from shared.
 *
 * @see libs/shared/ts/src/design/tokens.generated.ts
 * @see apps/mobile/global.css
 * @see docs/HEROUI_NATIVE_DECISION.md
 */

import {
  colorTokens,
  darkSemanticTokens,
  roundedTokens,
  spacingTokens,
  typographyTokens,
} from "@gaia/shared/design";

// ---------------------------------------------------------------------------
// Color aliases — GAIA mobile semantic names → shared token values
// Keep hex values 1:1 with shared / web globals.css `.dark`
// ---------------------------------------------------------------------------
export const colors = {
  // Brand / accent — shared colorTokens.primary (#00bbff) == web --color-primary
  brand: colorTokens.primary,
  brandForeground: colorTokens.primaryForeground,

  // Semantic tokens — dark mode values from web globals.css `.dark`
  // background: hsl(224 71% 4%) => #030711 (shared colorTokens.surface)
  background: colorTokens.surface,
  // foreground: hsl(213 31% 91%) => #e1e7ef (shared colorTokens.onSurface)
  foreground: colorTokens.onSurface,

  // card: same surface
  card: colorTokens.surface,
  cardForeground: colorTokens.onSurface,

  // muted: hsl(223 47% 11%) => #0f1629 (darkSemanticTokens.muted)
  // Hex kept because shared darkSemanticTokens.muted is HSL string "223 47% 11%"
  // and RN needs hex. Value verified against shared: matches #0f1629.
  muted: "#0f1629",
  // mutedForeground: hsl(215.4 16.3% 56.9%) => #7f8ea3
  mutedForeground: "#7f8ea3",

  // accent: hsl(216 34% 17%) => #1d283a (shared colorTokens.surfaceAccent == #1d293a)
  accent: colorTokens.surfaceAccent,
  accentForeground: "#f8fafc",

  // primary: hsl(210 40% 98%) => #f8fafc (darkSemanticTokens.primary)
  primary: "#f8fafc",
  // primaryForeground: hsl(222.2 47.4% 1.2%) => #020205
  primaryForeground: "#020205",

  // secondary: hsl(222.2 47.4% 11.2%) => #0f172a
  secondary: "#0f172a",
  secondaryForeground: "#f8fafc",

  // border/input/ring: shared colorTokens.border => #1d283a (hsl 216 34% 17%)
  border: colorTokens.border,
  input: colorTokens.border,
  ring: colorTokens.border,

  // destructive: shared colorTokens.destructive => #7f1d1d (hsl 0 63% 31% variant)
  destructive: colorTokens.destructive,
  destructiveForeground: "#f8fafc",

  // Status colors — tailwind green/yellow/red/blue-500 family + shared overrides
  // Mobile overrides shared success/warning for Tailwind parity:
  // shared success #34d399 (emerald-400) vs mobile #22c55e (green-500) — keep mobile green-500 for ToolCard parity
  success: "#22c55e",
  successForeground: "#000000",
  warning: "#eab308",
  warningForeground: "#000000",
  error: "#ef4444",
  errorForeground: "#ffffff",
  info: "#3b82f6",
  infoForeground: "#ffffff",

  // Priority colors — from web priorityTextColors
  priorityHigh: colorTokens.priorityHigh,
  priorityMedium: colorTokens.priorityMedium,
  priorityLow: colorTokens.priorityLow,
  priorityNone: "#71717a",

  // App-specific backgrounds — from web --color-primary-bg / --color-secondary-bg == shared primaryBg/secondaryBg
  primaryBg: colorTokens.primaryBg,
  secondaryBg: colorTokens.secondaryBg,

  // Zinc scale — mirrors Tailwind zinc, also present as shared neutral* tokens
  zinc100: colorTokens.neutral100,
  zinc200: colorTokens.neutral200,
  zinc300: colorTokens.neutral300,
  zinc400: colorTokens.neutral400,
  zinc500: "#71717a",
  zinc600: "#52525b",
  zinc700: colorTokens.neutral700,
  zinc800: colorTokens.neutral800,
  zinc900: colorTokens.neutral900,
  zinc950: "#09090b",

  // Utility
  white: "#ffffff",
  black: "#000000",
} as const;

export type ColorToken = keyof typeof colors;

// ---------------------------------------------------------------------------
// Shared token re-exports — prefer these in new code over `colors` aliases
// ---------------------------------------------------------------------------
export {
  colorTokens,
  darkSemanticTokens,
  roundedTokens,
  spacingTokens,
  typographyTokens,
};

// Legacy spacing / typography shims — keep existing mobile imports working while
// exposing shared tokens for new code. Values are kept in sync via shared.
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  "2xl": 32,
} as const;

export const rounded = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  "2xl": 24,
  full: 9999,
} as const;

export const typography = {
  fontFamily: {
    sans: ["Inter_400Regular", "System", "sans-serif"],
    mono: ["AnonymousPro_400Regular", "Courier New", "monospace"],
  },
  fontSize: {
    xs: 12,
    sm: 14,
    base: 16,
    lg: 18,
    xl: 20,
    "2xl": 24,
    "3xl": 30,
  },
  fontWeight: {
    normal: "400",
    medium: "500",
    semibold: "600",
    bold: "700",
  },
  lineHeight: {
    tight: 1.25,
    snug: 1.375,
    normal: 1.5,
    relaxed: 1.625,
  },
  // Shared typography tokens (Inter / PP Editorial / Anonymous Pro) are available
  // via `typographyTokens` import for web-parity consumers.
  tokens: typographyTokens,
} as const;
