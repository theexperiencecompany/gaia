/**
 * The baked logo as terminal lines: two pixels per cell, painted at the
 * terminal's colour level.
 * @module ui/header/logo
 */

import { Chalk, type ChalkInstance, type ColorSupportLevel } from "chalk";
import {
  LOGO_ANSI256,
  LOGO_PIXELS,
  LOGO_TRUECOLOR,
} from "./logo-cells.generated.js";

type Fill = keyof typeof LOGO_TRUECOLOR;
type Pixel = Fill | null;

/** 16 colours: the named slots, the only ones that mean the same in every theme. */
const ANSI16_FG = { d: "blue", m: "cyan", l: "cyanBright" } as const;
const ANSI16_BG = { d: "bgBlue", m: "bgCyan", l: "bgCyanBright" } as const;

const UPPER_HALF = "▀";
const LOWER_HALF = "▄";
const FULL_BLOCK = "█";

/** One terminal cell: a glyph, its foreground fill and the fill behind it. */
interface Cell {
  ch: string;
  fg: Pixel;
  bg: Pixel;
}

function pixel(ch: string | undefined): Pixel {
  return ch === "d" || ch === "m" || ch === "l" ? ch : null;
}

/**
 * A cell whose two pixels are one fill is a space on that background, so it
 * fills any line height without seams; edges are half blocks.
 */
function colourCell(top: Pixel, bottom: Pixel): Cell {
  if (top === null && bottom === null) return { ch: " ", fg: null, bg: null };
  if (top === bottom) return { ch: " ", fg: null, bg: top };
  if (top === null) return { ch: LOWER_HALF, fg: bottom, bg: null };
  return { ch: UPPER_HALF, fg: top, bg: bottom };
}

/** Without colour the mark is its silhouette. */
function silhouetteCell(top: Pixel, bottom: Pixel): Cell {
  const ch =
    top !== null && bottom !== null
      ? FULL_BLOCK
      : top !== null
        ? UPPER_HALF
        : bottom !== null
          ? LOWER_HALF
          : " ";
  return { ch, fg: null, bg: null };
}

function paint(chalk: ChalkInstance, { fg, bg }: Cell): ChalkInstance {
  let style = chalk;
  if (fg !== null) {
    style =
      chalk.level === 3
        ? style.hex(LOGO_TRUECOLOR[fg])
        : chalk.level === 2
          ? style.ansi256(LOGO_ANSI256[fg])
          : style[ANSI16_FG[fg]];
  }
  if (bg !== null) {
    style =
      chalk.level === 3
        ? style.bgHex(LOGO_TRUECOLOR[bg])
        : chalk.level === 2
          ? style.bgAnsi256(LOGO_ANSI256[bg])
          : style[ANSI16_BG[bg]];
  }
  return style;
}

/** Paint a row, one escape sequence per run of identical cells. */
function paintRow(chalk: ChalkInstance, cells: Cell[]): string {
  let line = "";
  let run = "";
  let runCell: Cell | null = null;
  for (const cell of cells) {
    if (runCell && (cell.fg !== runCell.fg || cell.bg !== runCell.bg)) {
      line += paint(chalk, runCell)(run);
      run = "";
    }
    runCell = cell;
    run += cell.ch;
  }
  return runCell ? line + paint(chalk, runCell)(run) : line;
}

/** Columns every line of the logo takes. */
export const LOGO_WIDTH = LOGO_PIXELS[0].length;

/** The logo's lines at a colour level, each exactly LOGO_WIDTH columns. */
export function logoLines(level: ColorSupportLevel): string[] {
  const rows = LOGO_PIXELS;
  const chalk = new Chalk({ level });
  const lines: string[] = [];
  for (let y = 0; y < rows.length; y += 2) {
    const top = rows[y] ?? "";
    const bottom = rows[y + 1] ?? "";
    const cells = [...top].map((ch, x) => {
      const t = pixel(ch);
      const b = pixel(bottom[x]);
      return level === 0 ? silhouetteCell(t, b) : colourCell(t, b);
    });
    lines.push(paintRow(chalk, cells));
  }
  return lines;
}
