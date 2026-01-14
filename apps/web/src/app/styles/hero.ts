import { heroui } from "@heroui/theme";

export default heroui({
  themes: {
    light: {
      colors: {
        background: "#ffffff",
        foreground: "#18181b",
        default: {
          50: "#fafafa",
          100: "#f4f4f5",
          200: "#e4e4e7",
          300: "#d4d4d8",
          400: "#a1a1aa",
          500: "#71717a",
          600: "#52525b",
          700: "#3f3f46",
          800: "#27272a",
          900: "#18181b",
          DEFAULT: "#f4f4f5",
          foreground: "#18181b",
        },
        content1: "#ffffff",
        content2: "#fafafa",
        content3: "#f4f4f5",
        content4: "#e4e4e7",
      },
    },
    dark: {
      colors: {
        background: "#09090b",
        foreground: "#fafafa",
        default: {
          50: "#18181b",
          100: "#27272a",
          200: "#3f3f46",
          300: "#52525b",
          400: "#71717a",
          500: "#a1a1aa",
          600: "#d4d4d8",
          700: "#e4e4e7",
          800: "#f4f4f5",
          900: "#fafafa",
          DEFAULT: "#3f3f46",
          foreground: "#fafafa",
        },
        content1: "#18181b",
        content2: "#27272a",
        content3: "#3f3f46",
        content4: "#52525b",
      },
    },
  },
});
