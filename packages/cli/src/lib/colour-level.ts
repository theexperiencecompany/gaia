/**
 * The one colour level the CLI paints at. Unlike chalk's own detection, it
 * keeps truecolor over SSH, which forwards TERM but not COLORTERM.
 * @module lib/colour-level
 */

import type { ColorSupportLevel } from "chalk";

export interface ColourEnvironment {
  env: NodeJS.ProcessEnv;
  isTTY: boolean;
  platform: NodeJS.Platform;
}

const FORCE_COLOR_LEVELS: Record<string, ColorSupportLevel> = {
  "": 1,
  true: 1,
  false: 0,
  "0": 0,
  "1": 1,
  "2": 2,
  "3": 3,
};

const TRUECOLOR_COLORTERMS = new Set(["truecolor", "24bit"]);

const TRUECOLOR_PROGRAMS = new Set([
  "iTerm.app",
  "WezTerm",
  "vscode",
  "ghostty",
]);

/** Ships TERM=xterm-256color but draws 24-bit colour wrongly on older macOS. */
const APPLE_TERMINAL = "Apple_Terminal";

/** Terminals whose TERM is a promise of 24-bit colour in every current release. */
const TRUECOLOR_TERM =
  /-256(color)?$|-direct$|-truecolor$|^tmux|^xterm-kitty$|^xterm-ghostty$|^alacritty|^wezterm|^foot|^contour/;

/** chalk's 16-colour TERM list. */
const ANSI16_TERM =
  /^screen|^xterm|^vt100|^vt220|^rxvt|color|ansi|cygwin|linux/;

/** NO_COLOR counts only when non-empty (no-color.org); FORCE_COLOR beats it, as in Node. */
export function colourLevel({
  env,
  isTTY,
  platform,
}: ColourEnvironment): ColorSupportLevel {
  const forced = env.FORCE_COLOR;
  if (forced !== undefined) {
    const level = FORCE_COLOR_LEVELS[forced];
    if (level === undefined) {
      throw new Error(
        `FORCE_COLOR=${JSON.stringify(forced)} is not one of 0-3, true or false`,
      );
    }
    return level;
  }
  const term = env.TERM ?? "";
  if (env.NO_COLOR || !isTTY || term === "dumb") return 0;
  if (TRUECOLOR_COLORTERMS.has(env.COLORTERM ?? "")) return 3;
  if (env.TERM_PROGRAM === APPLE_TERMINAL) return 2;
  if (TRUECOLOR_PROGRAMS.has(env.TERM_PROGRAM ?? "")) return 3;
  // Node 20+ runs only on Windows 10+, whose console renders 24-bit colour.
  if (platform === "win32" && (env.WT_SESSION || !term)) return 3;
  if (TRUECOLOR_TERM.test(term)) return 3;
  if (ANSI16_TERM.test(term) || env.COLORTERM) return 1;
  return 0;
}
