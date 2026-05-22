export const colors = {
  // Brand / accent — matches web --color-primary (#00bbff)
  brand: "#00bbff",
  brandForeground: "#000000",

  // Semantic tokens — dark mode values from web globals.css
  // background: hsl(224 71% 4%) = #030711
  background: "#030711",
  // foreground: hsl(213 31% 91%) = #e1e7ef
  foreground: "#e1e7ef",

  // card: hsl(224 71% 4%) = #030711
  card: "#030711",
  cardForeground: "#e1e7ef",

  // muted: hsl(223 47% 11%) = #0f1629
  muted: "#0f1629",
  // mutedForeground: hsl(215.4 16.3% 56.9%) = #7f8ea3
  mutedForeground: "#7f8ea3",

  // accent: hsl(216 34% 17%) = #1d283a
  accent: "#1d283a",
  accentForeground: "#f8fafc",

  // primary: hsl(210 40% 98%) = #f8fafc
  primary: "#f8fafc",
  // primaryForeground: hsl(222.2 47.4% 1.2%) = #020205
  primaryForeground: "#020205",

  // secondary: hsl(222.2 47.4% 11.2%) = #0f172a
  secondary: "#0f172a",
  secondaryForeground: "#f8fafc",

  // border: hsl(216 34% 17%) = #1d283a
  border: "#1d283a",
  input: "#1d283a",
  ring: "#1d283a",

  // destructive: hsl(0 63% 31%) = #811d1d
  destructive: "#811d1d",
  destructiveForeground: "#f8fafc",

  // Status colors — match Tailwind classes used in web (red-500, yellow-500, green-500, blue-500)
  success: "#22c55e",
  successForeground: "#000000",
  warning: "#eab308",
  warningForeground: "#000000",
  error: "#ef4444",
  errorForeground: "#ffffff",
  info: "#3b82f6",
  infoForeground: "#ffffff",

  // Priority colors — from web priorityTextColors (oklch converted, matching Tailwind red/yellow/blue)
  priorityHigh: "#ef4444",
  priorityMedium: "#eab308",
  priorityLow: "#3b82f6",
  priorityNone: "#71717a",

  // App-specific backgrounds — from web --color-primary-bg / --color-secondary-bg
  primaryBg: "#111111",
  secondaryBg: "#1a1a1a",

  // Zinc scale (mirrors Tailwind zinc) — single source of truth for raw hex usage
  zinc100: "#f4f4f5",
  zinc200: "#e4e4e7",
  zinc300: "#d4d4d8",
  zinc400: "#a1a1aa",
  zinc500: "#71717a",
  zinc600: "#52525b",
  zinc700: "#3f3f46",
  zinc800: "#27272a",
  zinc900: "#18181b",
  zinc950: "#09090b",

  // Utility
  white: "#ffffff",
  black: "#000000",
} as const;

export type ColorToken = keyof typeof colors;

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
} as const;
