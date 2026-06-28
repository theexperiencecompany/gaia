import { heroui } from "../../../../../node_modules/@heroui/theme/dist/index.mjs";

export default heroui({
  themes: {
    // GAIA's brand accent is cyan (#00bbff). HeroUI's default focus token is a
    // generic blue (#006FEE); pin it to the brand so focus rings never read as
    // off-brand anywhere in the app.
    light: { colors: { focus: "#00bbff" } },
    dark: { colors: { focus: "#00bbff" } },
  },
});
