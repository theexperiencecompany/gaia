import { createTheme } from "@openuidev/react-ui";

/**
 * GAIA OpenUI theme.
 *
 * Maps `@openuidev/react-ui`'s `--openui-*` design tokens onto GAIA's design
 * system (see DESIGN.md) so the adopted component library renders identically
 * to the rest of the product. Applied via `<ThemeProvider mode="dark"
 * darkTheme={gaiaOpenUITheme}>` around the OpenUI render root.
 *
 * Token → component mapping verified against the library CSS:
 * - `foreground` → Card "card" surface  → zinc-800 (#27272a)
 * - `sunk`       → Card "sunk" surface  → zinc-900 (#18181b)
 * - `textNeutral*` → all body/label text → zinc-100/400/500
 * - `radius3xl` (Card) defaults to 16px = GAIA `rounded-2xl`
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
  textSuccessPrimary: "#34d399", // emerald-400
  textAlertPrimary: "#fbbf24", // amber-400
  textDangerPrimary: "#f87171", // red-400
  textInfoPrimary: "#60a5fa", // blue-400
  successBackground: "rgba(52,211,153,0.12)",
  alertBackground: "rgba(251,191,36,0.16)",
  dangerBackground: "rgba(248,113,113,0.12)",
  infoBackground: "rgba(96,165,250,0.12)",
  borderSuccessEmphasis: "#34d399",
  borderAlertEmphasis: "#fbbf24",
  borderDangerEmphasis: "#f87171",
  borderInfoEmphasis: "#60a5fa",

  // ── Borders (GAIA cards are near-borderless; depth via tonal layering) ───
  borderDefault: "rgba(255,255,255,0.06)",
  borderInteractive: "rgba(255,255,255,0.12)",
  borderInteractiveSelected: "#00bbff",
  borderAccent: "rgba(0,187,255,0.2)",

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
