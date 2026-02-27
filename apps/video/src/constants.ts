// Video dimensions
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const FPS = 30;

// Colors
export const COLORS = {
  bg: "#111111",
  bgLight: "#ffffff",
  secondaryBg: "#1a1a1a",
  surface: "#27272a",
  primary: "#00bbff",
  white: "#ffffff",
  textDark: "#111111",
  zinc400: "#a1a1aa",
  zinc500: "#71717a",
  zinc600: "#52525b",
  zinc700: "#3f3f46",
  zinc800: "#27272a",
  zinc900: "#18181b",
} as const;

// Font families
export const FONTS = {
  display: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  body: '"Inter", system-ui, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
} as const;

// Transition durations (in frames)
export const TRANSITIONS = {
  fast: 8,
  normal: 12,
  slow: 15,
  reveal: 20,
} as const;

// Spring configs
export const SPRINGS = {
  smooth: { damping: 200 },
  snappy: { damping: 20, stiffness: 200 },
  natural: { damping: 18, stiffness: 120 },
  bouncy: { damping: 8, stiffness: 180 },
  cinematic: { damping: 22, stiffness: 80 },
} as const;
