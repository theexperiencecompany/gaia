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
import type { LogoSize } from "./logo.js";
import { renderHeader } from "./render.js";

export interface HeaderOptions {
  size?: LogoSize;
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

/** The header as ANSI lines, with one blank line above and below. */
async function headerLines({
  size = "small",
  showStatus = true,
  showUpdate = true,
}: HeaderOptions = {}): Promise<string[]> {
  const facts = {
    ...terminalSize(process.stdout),
    ...terminalAbilities(process.stdout),
  };
  const status = showStatus && facts.isTTY ? await probeInstance() : null;
  const lines = renderHeader({
    size,
    level: chalk.level,
    ...facts,
    version: CLI_VERSION,
    status,
    update: showUpdate ? availableUpdate() : null,
  });
  return ["", ...lines, ""];
}

export async function printHeader(options?: HeaderOptions): Promise<void> {
  process.stdout.write(`${(await headerLines(options)).join("\n")}\n`);
}

/** `gaia --version`: the large header, or exactly the version number for a script. */
export async function printVersion(): Promise<void> {
  if (!process.stdout.isTTY) {
    process.stdout.write(`${CLI_VERSION}\n`);
    return;
  }
  await printHeader({ size: "large" });
}
