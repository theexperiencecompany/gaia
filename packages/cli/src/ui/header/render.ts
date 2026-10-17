/**
 * The header every command opens with: the baked logo with the version,
 * tagline, instance status and an available update beside it. Pure: callers
 * pass in what they measured, so every surface renders the same lines.
 * @module ui/header/render
 */

import { Chalk, type ChalkInstance, type ColorSupportLevel } from "chalk";
import { MARK } from "../constants.js";
import { type LogoSize, logoLines, logoWidth } from "./logo.js";

/** What the header says about the local GAIA instance. */
export type InstanceStatus =
  | { running: true; webUrl: string; provider: string | null }
  | { running: false; installed: boolean };

export interface HeaderInput {
  size: LogoSize;
  level: ColorSupportLevel;
  /** Terminal width; the logo is dropped when it and the text do not fit. */
  columns: number;
  /** Terminal height; below MIN_LOGO_ROWS the logo would push the screen's own content off. */
  rows: number;
  isTTY: boolean;
  hyperlinks: boolean;
  version: string;
  /** null leaves the status line out. */
  status: InstanceStatus | null;
  /** The newer release to offer, or null. */
  update: string | null;
}

/** Columns between the logo and its text. */
export const LOGO_TEXT_GAP = 3;

/** Shortest terminal the logo is drawn on; an 80x24 screen keeps its rows for the command. */
const MIN_LOGO_ROWS = 40;

const COMPACT_SEPARATOR = " · ";

const TAGLINE = "Your proactive personal assistant";

/** A soft amber that reads on dark and light themes: news, not a warning. */
const UPDATE_ACCENT = { truecolor: "#af8700", ansi256: 136 } as const;

/** One text line: what it shows and how wide it is on screen. */
interface TextLine {
  plain: string;
  styled: string;
}

function hyperlink(url: string, enabled: boolean): string {
  return enabled ? `\u001b]8;;${url}\u001b\\${url}\u001b]8;;\u001b\\` : url;
}

function accent(chalk: ChalkInstance): ChalkInstance {
  if (chalk.level === 3) return chalk.hex(UPDATE_ACCENT.truecolor);
  if (chalk.level === 2) return chalk.ansi256(UPDATE_ACCENT.ansi256);
  return chalk.yellow;
}

function titleLine(chalk: ChalkInstance, version: string): TextLine {
  return {
    plain: `GAIA v${version}`,
    styled: `${chalk.bold("GAIA")} ${chalk.dim(`v${version}`)}`,
  };
}

function statusLine(
  chalk: ChalkInstance,
  status: InstanceStatus,
  hyperlinks: boolean,
): TextLine {
  if (!status.running) {
    const text = status.installed
      ? `${MARK.pending} Not running · start it with gaia start`
      : `${MARK.pending} Not installed · set it up with gaia up`;
    return { plain: text, styled: chalk.dim(text) };
  }
  const provider = status.provider ? ` · ${status.provider}` : "";
  return {
    plain: `● Running at ${status.webUrl}${provider}`,
    styled: `${chalk.green("●")} Running at ${hyperlink(status.webUrl, hyperlinks)}${chalk.dim(provider)}`,
  };
}

/** The status and update lines, in the order they are shown. */
function noticeLines(input: HeaderInput, chalk: ChalkInstance): TextLine[] {
  const lines: TextLine[] = [];
  if (input.status) {
    lines.push(statusLine(chalk, input.status, input.hyperlinks));
  }
  if (input.update) {
    const text = `Update available: ${input.update} · run gaia update`;
    lines.push({ plain: text, styled: accent(chalk)(text) });
  }
  return lines;
}

function plainWidth(line: TextLine): number {
  return [...line.plain].length;
}

/** The title, then each notice that still fits the width, on one line. */
function compactLine(input: HeaderInput, chalk: ChalkInstance): string {
  let line = titleLine(chalk, input.version);
  for (const notice of noticeLines(input, chalk)) {
    const joined = {
      plain: `${line.plain}${COMPACT_SEPARATOR}${notice.plain}`,
      styled: `${line.styled}${chalk.dim(COMPACT_SEPARATOR)}${notice.styled}`,
    };
    if (plainWidth(joined) > input.columns) break;
    line = joined;
  }
  return line.styled;
}

/** The header's lines: the logo with text centred beside it, or one compact line when it cannot show. */
export function renderHeader(input: HeaderInput): string[] {
  const chalk = new Chalk({ level: input.level });
  const text = [
    titleLine(chalk, input.version),
    { plain: TAGLINE, styled: chalk.dim(TAGLINE) },
    ...noticeLines(input, chalk),
  ];
  const width =
    logoWidth(input.size) + LOGO_TEXT_GAP + Math.max(...text.map(plainWidth));
  if (!input.isTTY || input.rows < MIN_LOGO_ROWS || width > input.columns) {
    return [compactLine(input, chalk)];
  }

  const logo = logoLines(input.size, input.level);
  const top = Math.floor((logo.length - text.length) / 2);
  return logo.map((line, y) => {
    const beside = text[y - top];
    return beside
      ? `${line}${" ".repeat(LOGO_TEXT_GAP)}${beside.styled}`
      : line;
  });
}
