#!/usr/bin/env node

import { Command } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../libs/shared/ts/src/cli/command-manifest.js";
import { runDev } from "./commands/dev/handler.js";
import { runInit } from "./commands/init/handler.js";
import { runSetup } from "./commands/setup/handler.js";
import { runStart } from "./commands/start/handler.js";
import { runStatus } from "./commands/status/handler.js";
import { runStop } from "./commands/stop/handler.js";
import { runLogs } from "./commands/stream-logs/handler.js";
import { CLI_VERSION } from "./lib/version.js";

const program = new Command();

program
  .name("gaia")
  .description("CLI tool for setting up and managing GAIA")
  .version(CLI_VERSION);

program
  .command("init")
  .description(CLI_COMMAND_DESCRIPTIONS.init)
  .option("--branch <branch>", "Git branch to clone")
  .action(async (options: { branch?: string }) => {
    await runInit({ branch: options.branch });
  });

program
  .command("setup")
  .description(CLI_COMMAND_DESCRIPTIONS.setup)
  .action(async () => {
    await runSetup();
  });

program
  .command("status")
  .description(CLI_COMMAND_DESCRIPTIONS.status)
  .action(async () => {
    await runStatus();
  });

program
  .command("start")
  .description(CLI_COMMAND_DESCRIPTIONS.start)
  .option("-b, --build", "Rebuild Docker images before starting")
  .option("--pull", "Pull latest base images before starting")
  .action(async (options: { build?: boolean; pull?: boolean }) => {
    await runStart({ build: options.build, pull: options.pull });
  });

program
  .command("dev [profile]")
  .description(CLI_COMMAND_DESCRIPTIONS.dev)
  .action(async (profile?: string) => {
    try {
      await runDev(profile);
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    }
  });

program
  .command("logs")
  .description(CLI_COMMAND_DESCRIPTIONS.logs)
  .action(async () => {
    try {
      await runLogs();
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    }
  });

program
  .command("stop")
  .description(CLI_COMMAND_DESCRIPTIONS.stop)
  .option(
    "--force-ports",
    "Aggressively stop processes listening on API/Web ports (may affect non-GAIA processes)",
  )
  .action(async (options: { forcePorts?: boolean }) => {
    await runStop({ forcePorts: options.forcePorts });
  });

// Show help when no command is given instead of silently running init
if (!process.argv.slice(2).length) {
  program.outputHelp();
  process.exit(0);
}

program.parse();
