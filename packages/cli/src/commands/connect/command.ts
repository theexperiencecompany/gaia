// `gaia connect` — fetches and runs the `gaia-connect` helper, which reads the
// local browser's cookies and uploads the sites you pick to GAIA.

import { Command } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../../../libs/shared/ts/src/cli/command-manifest.js";
import { ensureConnectBinary } from "./binary.js";
import { runConnectBinary } from "./run.js";

export async function runConnect(args: string[]): Promise<number> {
  const binary = await ensureConnectBinary(process.platform, process.arch);
  return await runConnectBinary(binary, args);
}

export const connectCommand = new Command("connect")
  .description(CLI_COMMAND_DESCRIPTIONS.connect)
  // Every flag belongs to gaia-connect, so commander must not parse or reject
  // them — they are forwarded byte-for-byte.
  .allowUnknownOption()
  .allowExcessArguments()
  .argument("[args...]", "flags forwarded to gaia-connect")
  .addHelpText(
    "after",
    `
Get an import code from GAIA -> Settings -> Browser -> Import, then run:
  npx @heygaia/cli connect --token <code>

Flags forwarded to gaia-connect:
  --token <code>      single-use import code from GAIA
  --api <origin>      GAIA API base URL (default https://api.heygaia.io)
  --browser <name>    browser name (skips the picker)
  --profile <name>    profile name or directory (skips the picker)
  --sites <domains>   comma-separated domains to sync (default: all)
  --json              robot mode: no TUI, structured JSON on stdout
  --list              with --json: list browsers, or sessions with --browser
`,
  )
  .action(async (args: string[]) => {
    try {
      process.exit(await runConnect(args));
    } catch (error) {
      console.error(
        `Error: ${error instanceof Error ? error.message : String(error)}`,
      );
      process.exit(1);
    }
  });
