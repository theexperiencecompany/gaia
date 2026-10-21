/**
 * The header for commands that print plain text (doctor, update, bots,
 * --version), measured from the real terminal.
 * @module ui/header/header-lines
 */

import chalk from "chalk";
import { supportsHyperlink } from "supports-hyperlinks";
import { terminalSize } from "../../lib/terminal-text.js";
import { CLI_VERSION } from "../../lib/version.js";
import { availableUpdate, probeInstance } from "./instance.js";
import { type InstanceStatus, renderHeader } from "./render.js";

export interface HeaderOptions {
  /** Whether to say if GAIA is running; off where the screen says it itself. */
  showStatus?: boolean;
  /** Whether to offer a newer release; off inside `gaia update`. */
  showUpdate?: boolean;
}

/** What a stream can show besides its size, shared by the Ink header. */
export function terminalAbilities(stream: NodeJS.WriteStream): {
  isTTY: boolean;
  hyperlinks: boolean;
} {
  return {
    isTTY: stream.isTTY === true,
    hyperlinks: supportsHyperlink(stream),
  };
}

/** The header as ANSI text in the screen's column (two in), with one blank line above and below. */
function headerText(
  status: InstanceStatus | null,
  showUpdate: boolean,
): string {
  const lines = renderHeader({
    level: chalk.level,
    ...terminalSize(process.stdout),
    ...terminalAbilities(process.stdout),
    version: CLI_VERSION,
    status,
    update: showUpdate ? availableUpdate() : null,
  });
  return ["", ...lines.map((line) => `  ${line}`), ""].join("\n");
}

export async function printHeader({
  showStatus = true,
  showUpdate = true,
}: HeaderOptions = {}): Promise<void> {
  const status =
    showStatus && process.stdout.isTTY === true ? await probeInstance() : null;
  process.stdout.write(`${headerText(status, showUpdate)}\n`);
}

/** The header `--help` opens with: no instance probe, so help stays instant. */
export function helpHeader(): string {
  return headerText(null, true);
}

/** `gaia --version`: the header, or exactly the version number for a script. */
export async function printVersion(): Promise<void> {
  if (!process.stdout.isTTY) {
    process.stdout.write(`${CLI_VERSION}\n`);
    return;
  }
  await printHeader();
}
