import { defaultTheme, extendTheme } from "@inkjs/ui";
import { THEME_COLOR } from "./constants.js";

/**
 * One accent everywhere: @inkjs/ui draws spinners blue and progress bars
 * magenta by default, which no other part of the CLI uses.
 */
export const cliTheme = extendTheme(defaultTheme, {
  components: {
    Spinner: {
      styles: {
        frame: () => ({ color: THEME_COLOR }),
      },
    },
    ProgressBar: {
      styles: {
        completed: () => ({ color: THEME_COLOR }),
      },
    },
  },
});
