import { defaultTheme, extendTheme } from "@inkjs/ui";
import { BAR, MARK, MARK_COLOR, THEME_COLOR } from "./constants.js";

type Variant = "success" | "error" | "warning" | "info";

/** @inkjs/ui's message variants drawn with the marks every plain report uses. */
const VARIANT_MARK = {
  success: "ok",
  error: "fail",
  warning: "warn",
  info: "active",
} as const;

/**
 * One accent and one set of marks everywhere: @inkjs/ui draws spinners blue,
 * progress bars magenta and its own ✔ ✖ ⚠, which no other part of the CLI uses.
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
      config: () => ({
        completedCharacter: BAR.done,
        remainingCharacter: BAR.rest,
      }),
    },
    StatusMessage: {
      styles: {
        icon: ({ variant }: { variant: Variant }) => ({
          color: MARK_COLOR[VARIANT_MARK[variant]],
        }),
      },
      config: ({ variant }: { variant: Variant }) => ({
        icon: MARK[VARIANT_MARK[variant]],
      }),
    },
    Alert: {
      styles: {
        icon: ({ variant }: { variant: Variant }) => ({
          color: MARK_COLOR[VARIANT_MARK[variant]],
        }),
      },
      config: ({ variant }: { variant: Variant }) => ({
        icon: MARK[VARIANT_MARK[variant]],
      }),
    },
  },
});
