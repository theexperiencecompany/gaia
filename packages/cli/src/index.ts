#!/usr/bin/env node

import { Command } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../libs/shared/ts/src/cli/command-manifest.js";
import { bridgeCommand } from "./commands/bridge/command.js";
import { runDev } from "./commands/dev/handler.js";
import { runDoctor } from "./commands/doctor/handler.js";
import { runInit } from "./commands/init/handler.js";
import { runSetup } from "./commands/setup/handler.js";
import { runStart } from "./commands/start/handler.js";
import { runStatus } from "./commands/status/handler.js";
import { runStop } from "./commands/stop/handler.js";
import { runLogs } from "./commands/stream-logs/handler.js";
import { runUp } from "./commands/up/handler.js";
import { CLI_VERSION } from "./lib/version.js";

const program = new Command();

/** Raw parsed options for `gaia up` (commander negates --no-start to `start`). */
interface UpCliOptions {
  yes?: boolean;
  llmKey?: string;
  llmProvider?: string;
  apiPort?: number;
  webPort?: number;
  pull?: boolean;
  build?: boolean;
  /** False when --no-start is passed (commander negatable option). */
  start?: boolean;
  forceDevTree?: boolean;
}

program
  .name("gaia")
  .description("CLI tool for setting up and managing GAIA")
  .version(CLI_VERSION);

program.addCommand(bridgeCommand);

program
  .command("init")
  .description(CLI_COMMAND_DESCRIPTIONS.init)
  .option("--branch <branch>", "Git branch to clone")
  .action(async (options: { branch?: string }) => {
    await runInit({ branch: options.branch });
  });

program
  .command("up")
  .description(CLI_COMMAND_DESCRIPTIONS.up)
  .option("--yes", "Accept all defaults (no prompts)")
  .option("--llm-key <key>", "LLM API key for first boot")
  .option(
    "--llm-provider <provider>",
    "LLM provider for --llm-key: openrouter, gemini, or custom",
  )
  .option("--api-port <port>", "Host port for the API", Number.parseInt)
  .option("--web-port <port>", "Host port for the web app", Number.parseInt)
  .option("--pull", "Pull pre-built images only (fail instead of building)")
  .option("-b, --build", "Build images locally before starting")
  .option("--no-start", "Configure environment only; do not start services")
  .option(
    "--force-dev-tree",
    "Allow operating on a developer checkout that is not the recorded install",
  )
  .action(async (options: UpCliOptions) => {
    const { start, ...rest } = options;
    await runUp({
      ...rest,
      llmProvider:
        rest.llmProvider === "openrouter" ||
        rest.llmProvider === "gemini" ||
        rest.llmProvider === "custom"
          ? rest.llmProvider
          : undefined,
      noStart: start === false,
    });
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
  .command("doctor")
  .description(CLI_COMMAND_DESCRIPTIONS.doctor)
  .action(async () => {
    await runDoctor();
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
