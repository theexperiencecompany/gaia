/**
 * Workflows feature color tokens.
 *
 * Mobile design tokens for the workflows surface. Where a project-wide token
 * exists in `apps/mobile/src/theme/`, prefer that. These are feature-local
 * literals consolidated from inline hex values used across workflow screens.
 */

export const WORKFLOW_COLORS = {
  // Surfaces
  screenBg: "#131416",
  cardBg: "rgba(39,39,42,0.30)",
  cardBgActive: "rgba(39,39,42,0.70)",
  surfaceMuted: "rgba(255,255,255,0.05)",
  surfaceMutedAlt: "rgba(255,255,255,0.07)",
  surfaceTinted: "rgba(255,255,255,0.04)",
  borderSubtle: "rgba(255,255,255,0.08)",

  // Text
  textPrimary: "#ffffff",
  textSecondary: "#e4e4e7",
  textBody: "#c0c6cf",
  textMuted: "#a1a1aa",
  textFaint: "#8e8e93",
  textZinc500: "#71717a",
  textZinc600: "#52525b",
  textZinc700: "#3f3f46",

  // Accent (primary)
  primary: "#00bbff",
  primaryPressed: "#0099dd",
  onPrimary: "#000000",
  primarySubtle: "rgba(0,187,255,0.10)",
  primarySubtleAlt: "rgba(0,187,255,0.15)",
  primaryFaint: "rgba(0,187,255,0.06)",
  primaryBorder: "rgba(0,187,255,0.40)",

  // Bottom sheet chrome
  sheetBg: "#141414",
  handleIndicator: "#3a3a3c",

  // Status palette
  successText: "#22c55e",
  successBg: "rgba(34,197,94,0.12)",
  dangerText: "#ef4444",
  dangerBg: "rgba(239,68,68,0.12)",
  warningText: "#f59e0b",
  warningBg: "rgba(245,158,11,0.12)",

  // Misc
  violet: "#a78bfa",
  violetBg: "rgba(167,139,250,0.10)",
} as const;
