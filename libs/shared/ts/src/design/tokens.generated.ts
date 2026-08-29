/**
 * AUTO-GENERATED — do not edit directly.
 * Source: apps/web/src/app/styles/globals.css (@theme + :root/.dark) + config/design.tokens.json (DTCG)
 * Generator: pnpm run tokens:export → config/design.tokens.json, parsed by design/tokens.generated.ts codegen
 * To regenerate: node scripts/codegen-tokens.mjs (reads globals.css and design.tokens.json) or re-run this file's inline generator
 *
 * This module exposes GAIA design tokens as typed JS constants for shared use
 * across web, mobile, and desktop. Values mirror CSS variables so JS and CSS stay in sync.
 */

// ---------------------------------------------------------------------------
// DTCG tokens from config/design.tokens.json (source: DESIGN.md)
// ---------------------------------------------------------------------------

export const colorTokens = {
  primary: "#00bbff",
  primaryForeground: "#000000",
  primaryBg: "#111111",
  secondaryBg: "#1a1a1a",
  selectionBg: "#00364b",
  selectionFg: "#00bbff",
  neutral100: "#f4f4f5",
  neutral200: "#e4e4e7",
  neutral300: "#d4d4d8",
  neutral400: "#a1a1aa",
  neutral700: "#3f3f46",
  neutral800: "#27272a",
  neutral900: "#18181b",
  surface: "#030711",
  onSurface: "#e1e7ef",
  surfaceAccent: "#1d293a",
  border: "#1d293a",
  success: "#34d399",
  warning: "#fbbf24",
  error: "#f87171",
  info: "#60a5fa",
  destructive: "#7f1d1d",
  priorityHigh: "#ef4444",
  priorityMedium: "#eab308",
  priorityLow: "#3b82f6",
} as const;

export const spacingTokens = {
  none: "0px",
  xs: "4px",
  sm: "8px",
  md: "12px",
  lg: "16px",
  xl: "24px",
  xxl: "32px",
  gutter: "16px",
} as const;

export const roundedTokens = {
  none: "0px",
  sm: "6px",
  md: "8px",
  lg: "12px",
  xl: "16px",
  xxl: "24px",
  full: "9999px",
} as const;

export const typographyTokens = {
  display: {
    fontFamily: "PP Editorial New",
    fontSize: "48px",
    fontWeight: 200,
    lineHeight: 1.1,
    letterSpacing: "-0.02em",
  },
  headlineLg: {
    fontFamily: "Inter",
    fontSize: "30px",
    fontWeight: 700,
    lineHeight: 1.2,
  },
  headlineMd: {
    fontFamily: "Inter",
    fontSize: "24px",
    fontWeight: 700,
    lineHeight: 1.25,
  },
  headlineSm: {
    fontFamily: "Inter",
    fontSize: "20px",
    fontWeight: 700,
    lineHeight: 1.3,
  },
  titleLg: {
    fontFamily: "Inter",
    fontSize: "18px",
    fontWeight: 700,
    lineHeight: 1.4,
  },
  titleMd: {
    fontFamily: "Inter",
    fontSize: "16px",
    fontWeight: 600,
    lineHeight: 1.4,
  },
  titleSm: {
    fontFamily: "Inter",
    fontSize: "14px",
    fontWeight: 600,
    lineHeight: 1.4,
  },
  bodyMd: {
    fontFamily: "Inter",
    fontSize: "16px",
    fontWeight: 400,
    lineHeight: 1.5,
  },
  bodySm: {
    fontFamily: "Inter",
    fontSize: "14px",
    fontWeight: 400,
    lineHeight: 1.5,
  },
  bodyXs: {
    fontFamily: "Inter",
    fontSize: "12px",
    fontWeight: 400,
    lineHeight: 1.5,
  },
  label: {
    fontFamily: "Inter",
    fontSize: "12px",
    fontWeight: 500,
    lineHeight: 1.4,
    letterSpacing: "0.05em",
  },
  code: {
    fontFamily: "Anonymous Pro",
    fontSize: "14px",
    fontWeight: 400,
    lineHeight: 1.5,
  },
} as const;

// ---------------------------------------------------------------------------
// CSS variables from apps/web/src/app/styles/globals.css
// ---------------------------------------------------------------------------

/**
 * @theme block — Tailwind v4 theme tokens. These are the runtime CSS variables
 * emitted by Tailwind's @theme and consumed as utility classes (e.g. bg-primary).
 */
export const themeCssVars = {
  fontSans: "var(--font-inter), system-ui, sans-serif",
  fontSerif: "var(--font-aeonik), system-ui, sans-serif",
  fontMono:
    'var(--font-geist-mono), ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, "DejaVu Sans Mono", monospace',
  colorSecondaryBg: "#1a1a1a",
  colorPrimaryBg: "#111111",
  normalBg: "var(--color-primary-bg)",
  colorPrimary: "#00bbff",
  colorPrimaryForeground: "#000000",
  colorWhite: "#ffffff",
  colorWhiteForeground: "#000000",
  colorCommandBg: "#1e293b",
  colorCommandText: "#f8fafc",
  colorCommandBorder: "#334155",
  colorSidebar: "hsl(var(--sidebar-background))",
  colorSidebarForeground: "hsl(var(--sidebar-foreground))",
  colorSidebarPrimary: "hsl(var(--sidebar-primary))",
  colorSidebarPrimaryForeground: "hsl(var(--sidebar-primary-foreground))",
  colorSidebarAccent: "hsl(var(--sidebar-accent))",
  colorSidebarAccentForeground: "hsl(var(--sidebar-accent-foreground))",
  colorSidebarBorder: "hsl(var(--sidebar-border))",
  colorSidebarRing: "hsl(var(--sidebar-ring))",
  radius: "0.5rem",
  borderRadiusLg: "var(--radius)",
  borderRadiusMd: "calc(var(--radius) - 2px)",
  borderRadiusSm: "calc(var(--radius) - 4px)",
  animateShine: "shine 1s linear infinite",
  animateShineBorder: "shine-border var(--duration, 14s) infinite linear",
  animateOrbit: "orbit calc(var(--duration) * 1s) linear infinite",
  animateGrid: "grid 15s linear infinite",
  animateAccordionDown: "accordion-down 0.2s ease-out",
  animateAccordionUp: "accordion-up 0.2s ease-out",
  animateShinyText: "shiny-text 8s infinite",
  animateShimmer: "shimmer 2s linear infinite",
  animateShake: "shake 0.7s ease-in-out",
  animateScaleIn: "scale-in 0.4s ease-out forwards",
  animateCaretBlink: "caret-blink 1.25s ease-out infinite",
  animateMarquee: "marquee var(--duration) infinite linear",
  animateMarqueeVertical: "marquee-vertical var(--duration) linear infinite",
  colorSidebarRingVar: "var(--sidebar-ring)",
  colorSidebarBorderVar: "var(--sidebar-border)",
  colorSidebarAccentForegroundVar: "var(--sidebar-accent-foreground)",
  colorSidebarAccentVar: "var(--sidebar-accent)",
  colorSidebarPrimaryForegroundVar: "var(--sidebar-primary-foreground)",
  colorSidebarPrimaryVar: "var(--sidebar-primary)",
  colorSidebarForegroundVar: "var(--sidebar-foreground)",
  colorSidebarVar: "var(--sidebar)",
} as const;

/**
 * Raw CSS variable map mirroring globals.css `:root` + `.dark` + `@theme`.
 * Keys are the CSS custom property names; values are the declared values.
 * Use for codegen or runtime CSS-in-JS bridges.
 */
export const cssVarMap = {
  "--font-sans": "var(--font-inter), system-ui, sans-serif",
  "--font-serif": "var(--font-aeonik), system-ui, sans-serif",
  "--font-mono":
    'var(--font-geist-mono), ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, "DejaVu Sans Mono", monospace',
  "--color-secondary-bg": "#1a1a1a",
  "--color-primary-bg": "#111111",
  "--normal-bg": "var(--color-primary-bg)",
  "--color-primary": "#00bbff",
  "--color-primary-foreground": "#000000",
  "--color-white": "#ffffff",
  "--color-white-foreground": "#000000",
  "--color-command-bg": "#1e293b",
  "--color-command-text": "#f8fafc",
  "--color-command-border": "#334155",
  "--color-sidebar": "hsl(var(--sidebar-background))",
  "--color-sidebar-foreground": "hsl(var(--sidebar-foreground))",
  "--color-sidebar-primary": "hsl(var(--sidebar-primary))",
  "--color-sidebar-primary-foreground": "hsl(var(--sidebar-primary-foreground))",
  "--color-sidebar-accent": "hsl(var(--sidebar-accent))",
  "--color-sidebar-accent-foreground": "hsl(var(--sidebar-accent-foreground))",
  "--color-sidebar-border": "hsl(var(--sidebar-border))",
  "--color-sidebar-ring": "hsl(var(--sidebar-ring))",
  "--radius": "0.5rem",
  "--border-radius-lg": "var(--radius)",
  "--border-radius-md": "calc(var(--radius) - 2px)",
  "--border-radius-sm": "calc(var(--radius) - 4px)",
  "--animate-shine": "shine 1s linear infinite",
  "--animate-shine-border": "shine-border var(--duration, 14s) infinite linear",
  "--animate-orbit": "orbit calc(var(--duration) * 1s) linear infinite",
  "--animate-grid": "grid 15s linear infinite",
  "--animate-accordion-down": "accordion-down 0.2s ease-out",
  "--animate-accordion-up": "accordion-up 0.2s ease-out",
  "--animate-shiny-text": "shiny-text 8s infinite",
  "--animate-shimmer": "shimmer 2s linear infinite",
  "--animate-shake": "shake 0.7s ease-in-out",
  "--animate-scale-in": "scale-in 0.4s ease-out forwards",
  "--animate-caret-blink": "caret-blink 1.25s ease-out infinite",
  "--animate-marquee": "marquee var(--duration) infinite linear",
  "--animate-marquee-vertical": "marquee-vertical var(--duration) linear infinite",
} as const;

// ---------------------------------------------------------------------------
// Light / Dark semantic tokens (mirrors :root and .dark blocks)
// ---------------------------------------------------------------------------

export const lightSemanticTokens = {
  herouiPrimary: "#00bbff",
  herouiPrimaryForeground: "#000000",
  herouiFocus: "#00bbff",
  herouiWhite: "#ffffff",
  herouiWhiteForeground: "#000000",
  background: "0 0% 100%",
  foreground: "222.2 47.4% 11.2%",
  muted: "210 40% 96.1%",
  mutedForeground: "215.4 16.3% 46.9%",
  popover: "0 0% 100%",
  popoverForeground: "222.2 47.4% 11.2%",
  border: "214.3 31.8% 91.4%",
  input: "214.3 31.8% 91.4%",
  card: "0 0% 100%",
  cardForeground: "222.2 47.4% 11.2%",
  primary: "222.2 47.4% 11.2%",
  primaryForeground: "210 40% 98%",
  secondary: "210 40% 96.1%",
  secondaryForeground: "222.2 47.4% 11.2%",
  accent: "210 40% 96.1%",
  accentForeground: "222.2 47.4% 11.2%",
  destructive: "0 100% 50%",
  destructiveForeground: "210 40% 98%",
  ring: "215 20.2% 65.1%",
  radius: "0.5rem",
} as const;

export const darkSemanticTokens = {
  herouiPrimary: "#00bbff",
  herouiPrimaryForeground: "#000000",
  herouiFocus: "#00bbff",
  herouiWhite: "#ffffff",
  herouiWhiteForeground: "#000000",
  background: "224 71% 4%",
  foreground: "213 31% 91%",
  muted: "223 47% 11%",
  mutedForeground: "215.4 16.3% 56.9%",
  accent: "216 34% 17%",
  accentForeground: "210 40% 98%",
  popover: "224 71% 4%",
  popoverForeground: "215 20.2% 65.1%",
  border: "216 34% 17%",
  input: "216 34% 17%",
  card: "224 71% 4%",
  cardForeground: "213 31% 91%",
  primary: "210 40% 98%",
  primaryForeground: "222.2 47.4% 1.2%",
  secondary: "222.2 47.4% 11.2%",
  secondaryForeground: "210 40% 98%",
  destructive: "0 63% 31%",
  destructiveForeground: "210 40% 98%",
  ring: "216 34% 17%",
  radius: "0.5rem",
} as const;

export const sidebarTokens = {
  light: {
    foreground: "240 5.3% 26.1%",
    primary: "240 5.9% 10%",
    primaryForeground: "0 0% 98%",
    accent: "240 4.8% 95.9%",
    accentForeground: "240 5.9% 10%",
    border: "220 13% 91%",
    ring: "217.2 91.2% 59.8%",
    width: "260px",
  },
  dark: {
    foreground: "240 4.8% 95.9%",
    primary: "224.3 76.3% 48%",
    primaryForeground: "0 0% 100%",
    accent: "240 3.7% 15.9%",
    accentForeground: "240 4.8% 95.9%",
    border: "240 3.7% 15.9%",
    ring: "217.2 91.2% 59.8%",
    width: "260px",
  },
} as const;

// ---------------------------------------------------------------------------
// Unified export
// ---------------------------------------------------------------------------

export const designTokens = {
  color: colorTokens,
  spacing: spacingTokens,
  rounded: roundedTokens,
  typography: typographyTokens,
  themeVars: themeCssVars,
  cssVarMap,
  light: lightSemanticTokens,
  dark: darkSemanticTokens,
  sidebar: sidebarTokens,
} as const;

export type DesignTokens = typeof designTokens;
export type ColorTokens = typeof colorTokens;
export type SpacingTokens = typeof spacingTokens;
export type RoundedTokens = typeof roundedTokens;
