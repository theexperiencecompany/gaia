// Import from the ThemeProvider subpath, not the package barrel. The barrel
// (@openuidev/react-ui) statically pulls in recharts, react-markdown,
// react-syntax-highlighter and react-day-picker (~1.5-2 MB), which then land on
// EVERY route via RootProviders — including the desktop login screen. The
// subpath re-exports createTheme + ThemeProvider with none of that weight.
import { createTheme } from "@openuidev/react-ui/ThemeProvider";

/**
 * GAIA OpenUI theme.
 *
 * Maps `@openuidev/react-ui`'s `--openui-*` tokens onto GAIA's design system
 * (DESIGN.md), applied via `<ThemeProvider mode="dark" darkTheme={gaiaOpenUITheme}>`.
 * Verified against the library CSS: `foreground`→Card "card" zinc-800
 * (#27272a), `sunk`→Card "sunk" zinc-900 (#18181b), `textNeutral*`→body/label
 * zinc-100/400/500, `radius3xl`(Card)=16px=GAIA `rounded-2xl`.
 */

// GAIA data-viz palettes (DESIGN.md). Cyan-led, matching the previous OpenUI charts.
const CHART_PALETTE = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];
const PIE_PALETTE = ["#00bbff", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];

export const gaiaOpenUITheme = createTheme({
  // ── Surfaces ────────────────────────────────────────────────────────────
  background: "#18181b", // zinc-900 base
  foreground: "#27272a", // zinc-800 — Card "card" surface (outer)
  popoverBackground: "#27272a",
  sunk: "#18181b", // zinc-900 — Card "sunk" well (nested)
  sunkLight: "rgba(255,255,255,0.02)",
  sunkDeep: "rgba(255,255,255,0.08)",
  elevatedLight: "rgba(255,255,255,0.04)",
  elevated: "rgba(255,255,255,0.06)",
  elevatedStrong: "rgba(255,255,255,0.12)",
  elevatedIntense: "rgba(255,255,255,0.24)",
  overlay: "rgba(0,0,0,0.6)",

  // ── Text ────────────────────────────────────────────────────────────────
  textNeutralPrimary: "#f4f4f5", // zinc-100
  textNeutralSecondary: "#a1a1aa", // zinc-400
  textNeutralTertiary: "#71717a", // zinc-500
  textNeutralLink: "#00bbff",
  textBrand: "#00bbff",
  textAccentPrimary: "#000000", // text on a primary (#00bbff) fill

  // ── Brand / interactive ─────────────────────────────────────────────────
  interactiveAccentDefault: "#00bbff",
  interactiveAccentHover: "#33c9ff",
  interactiveAccentPressed: "#00a6e0",
  interactiveAccentDisabled: "rgba(0,187,255,0.4)",

  // ── Status (text + tinted backgrounds + emphasis borders) ───────────────
  textSuccessPrimary: "#10b981", // emerald-500
  textAlertPrimary: "#f59e0b", // amber-500
  textDangerPrimary: "#ef4444", // red-500
  textInfoPrimary: "#3b82f6", // blue-500
  successBackground: "rgba(16,185,129,0.1)",
  alertBackground: "rgba(245,158,11,0.1)",
  dangerBackground: "rgba(239,68,68,0.1)",
  infoBackground: "rgba(59,130,246,0.1)",
  borderSuccessEmphasis: "#10b981",
  borderAlertEmphasis: "#f59e0b",
  borderDangerEmphasis: "#ef4444",
  borderInfoEmphasis: "#3b82f6",

  // ── Borders — flat design, no outlines (depth comes from tonal layering;
  //    keep only the brand "selected" indicator) ───────────────────────────
  borderDefault: "transparent",
  borderInteractive: "transparent",
  borderInteractiveEmphasis: "transparent",
  borderAccent: "transparent",
  borderAccentEmphasis: "transparent",
  borderInteractiveSelected: "#00bbff",

  // ── Chat ────────────────────────────────────────────────────────────────
  chatUserResponseBg: "rgba(255,255,255,0.08)",
  chatUserResponseText: "#f4f4f5",

  // ── Typography (GAIA fonts via next/font CSS variables) ──────────────────
  fontBody: "var(--font-inter), Inter, sans-serif",
  fontHeading: "var(--font-inter), Inter, sans-serif",
  fontLabel: "var(--font-inter), Inter, sans-serif",
  fontNumbers: "var(--font-inter), Inter, sans-serif",
  fontCode:
    "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",

  // ── Spacing (tightened toward GAIA's p-4 / gap-3 — react-ui defaults run
  //    roomier: Card padding = space-l, Card gap = space-xl) ────────────────
  spaceM: "10px",
  spaceML: "12px",
  spaceL: "16px", // Card padding → GAIA p-4
  spaceXl: "14px", // Card content gap → tighter than the 24px default
  space2xl: "28px",

  // ── Radius — slightly rounder per GAIA's design language ─────────────────
  radiusS: "8px", // chips (Tag sm)
  radiusM: "12px", // chips (Tag md), small controls
  radiusL: "12px", // buttons / inputs
  radiusXl: "14px",
  radius2xl: "16px",
  radius3xl: "24px", // cards (react-ui Card uses radius-3xl)

  // ── Shadows — flat cards; keep large shadows only for true overlays ──────
  shadow0: "none",
  shadowS: "none",
  shadowM: "none",
  shadowL: "none",

  // ── Charts ──────────────────────────────────────────────────────────────
  defaultChartPalette: CHART_PALETTE,
  barChartPalette: CHART_PALETTE,
  lineChartPalette: CHART_PALETTE,
  areaChartPalette: CHART_PALETTE,
  radarChartPalette: CHART_PALETTE,
  horizontalBarChartPalette: CHART_PALETTE,
  pieChartPalette: PIE_PALETTE,
  radialChartPalette: PIE_PALETTE,
});
