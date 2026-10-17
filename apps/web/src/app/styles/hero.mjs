import { heroui } from "@heroui/theme";

// GAIA's brand accent is cyan (#00bbff). HeroUI's flat/light/bordered variants read
// the primary scale (primary-600, -700…), not only DEFAULT, so the whole scale is
// brand cyan. Dark mode runs it lightest-last, as HeroUI's own dark palettes do.
const PRIMARY_LIGHT = {
  50: "#e5f8ff",
  100: "#ccf1ff",
  200: "#99e4ff",
  300: "#66d6ff",
  400: "#33c9ff",
  500: "#00bbff",
  600: "#0096cc",
  700: "#007099",
  800: "#004b66",
  900: "#002533",
  DEFAULT: "#00bbff",
  foreground: "#000000",
};

const PRIMARY_DARK = {
  50: "#002533",
  100: "#004b66",
  200: "#007099",
  300: "#0096cc",
  400: "#00a8e6",
  500: "#00bbff",
  600: "#33c9ff",
  700: "#66d6ff",
  800: "#99e4ff",
  900: "#ccf1ff",
  DEFAULT: "#00bbff",
  foreground: "#000000",
};

export default heroui({
  themes: {
    light: { colors: { primary: PRIMARY_LIGHT, focus: "#00bbff" } },
    dark: { colors: { primary: PRIMARY_DARK, focus: "#00bbff" } },
  },
});
