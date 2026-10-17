#!/usr/bin/env node

import { Command, Option } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../libs/shared/ts/src/cli/command-manifest.js";
import { runBackupCommand } from "./commands/backup/handler.js";
import { botsCommand } from "./commands/bots/command.js";
import { bridgeCommand } from "./commands/bridge/command.js";
import { connectCommand } from "./commands/connect/command.js";
import { runDev } from "./commands/dev/handler.js";
import { runDoctor } from "./commands/doctor/handler.js";
import { runInit } from "./commands/init/handler.js";
import { runRestoreCommand } from "./commands/restore/handler.js";
import { runSetup } from "./commands/setup/handler.js";
import { runStart } from "./commands/start/handler.js";
import { runStatus } from "./commands/status/handler.js";
import { runStop } from "./commands/stop/handler.js";
import { runLogs } from "./commands/stream-logs/handler.js";
import { runUp } from "./commands/up/handler.js";
import { runUpdate, type UpdateOptions } from "./commands/update/handler.js";
import { LLM_PROVIDERS, type LlmProvider } from "./lib/llm-flags.js";
import { printVersion } from "./ui/header/header-lines.js";

/** The root flags that print the version (with the header on a terminal). */
const VERSION_FLAGS = new Set(["-V", "--version"]);

const program = new Command();

/** Raw parsed options for `gaia up` (commander negates --no-start to `start`). */
interface UpCliOptions {
  yes?: boolean;
  llmKey?: string;
  /** Restricted to LLM_PROVIDERS by the option's choices. */
  llmProvider?: LlmProvider;
  llmBaseUrl?: string;
  llmModel?: string;
  webPort?: number;
  domain?: string;
  build?: boolean;
  /** Undefined unless --code-sandbox or --no-code-sandbox is passed. */
  codeSandbox?: boolean;
  /** False when --no-start is passed (commander negatable option). */
  start?: boolean;
  forceDevTree?: boolean;
}
/** Help heading for the commands only people working on GAIA's code need. */
const CONTRIBUTOR_COMMANDS = "For contributors:";

program
  .name("gaia")
  .description(
    "Run GAIA, your proactive personal assistant, on your own computer or server",
  )
  .option("-V, --version", "Show the CLI's version")
  .helpOption("-h, --help", "Show help for a command")
  .helpCommand("help [command]", "Show help for a command")
  // Root options only before the subcommand, so `gaia update --version <tag>`
  // reaches update instead of printing the CLI version.
  .enablePositionalOptions()
  .addHelpText("after", "\nNew here? Run: gaia up");

// Commands in the order a self-hoster meets them: install, check, stop and
// start, update, troubleshoot, then the extras.
program
  .command("up")
  .description(CLI_COMMAND_DESCRIPTIONS.up)
  .option(
    "--yes",
    "Answer yes to every question, including installing Git and Docker",
  )
  .addOption(
    new Option(
      "--llm-provider <provider>",
      "AI provider to save once GAIA is running (checked first, as the setup page does)",
    ).choices(LLM_PROVIDERS),
  )
  .option(
    "--llm-key <key>",
    "API key for --llm-provider (openrouter, gemini, openai, custom)",
  )
  .option(
    "--llm-base-url <url>",
    "Address of --llm-provider ollama (default http://host.docker.internal:11434) or custom",
  )
  .option(
    "--llm-model <model>",
    "Model for --llm-provider ollama (optional) or custom (required)",
  )
  .option(
    "--web-port <port>",
    "Port GAIA is served on (default 3000)",
    Number.parseInt,
  )
  .option(
    "--domain <domain>",
    "Serve GAIA at https://<domain> with an automatic certificate (uses ports 80 and 443)",
  )
  .option(
    "-b, --build",
    "Build GAIA from source on this machine instead of downloading it (slow)",
  )
  .option(
    "--code-sandbox",
    "Let GAIA run code in containers on this machine (gives it control of Docker; kept on later starts)",
  )
  .option(
    "--no-code-sandbox",
    "Turn that off again (running code then needs an E2B key)",
  )
  .option("--no-start", "Set everything up, but don't start GAIA")
  .option(
    "--force-dev-tree",
    "Allow 'gaia up' on a development copy of GAIA that isn't your install",
  )
  .action(async (options: UpCliOptions) => {
    const { start, ...rest } = options;
    await runUp({ ...rest, noStart: start === false });
  });

program
  .command("status")
  .description(CLI_COMMAND_DESCRIPTIONS.status)
  .option("--watch", "Stay open; press r to check again")
  .action(async (options: { watch?: boolean }) => {
    await runStatus({ watch: options.watch });
  });

program
  .command("stop")
  .description(CLI_COMMAND_DESCRIPTIONS.stop)
  .option(
    "--force-ports",
    "Also stop whatever else listens on GAIA's ports (may stop other programs)",
  )
  .action(async (options: { forcePorts?: boolean }) => {
    await runStop({ forcePorts: options.forcePorts });
  });

program
  .command("start")
  .description(CLI_COMMAND_DESCRIPTIONS.start)
  .option("-b, --build", "Build GAIA from source before starting (slow)")
  .option("--pull", "Download GAIA's images again before starting")
  .action(async (options: { build?: boolean; pull?: boolean }) => {
    await runStart({
      build: options.build,
      pull: options.pull ? "always" : undefined,
    });
  });

program
  .command("update")
  .description(CLI_COMMAND_DESCRIPTIONS.update)
  .option("--yes", "Update without asking")
  .option(
    "--version <tag>",
    "Move to this GAIA release (v<x.y.z>) instead of the one this CLI installs",
  )
  .option(
    "--git",
    "For development copies: pull the current branch and rebuild from source",
  )
  .action(async (options: UpdateOptions) => {
    await runUpdate(options);
  });

program
  .command("doctor")
  .description(CLI_COMMAND_DESCRIPTIONS.doctor)
  .action(async () => {
    await runDoctor();
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

program.addCommand(botsCommand);
program.addCommand(connectCommand);
program.addCommand(bridgeCommand);

program
  .command("backup")
  .description(CLI_COMMAND_DESCRIPTIONS.backup)
  .option("--output <dir>", "Folder to save the backup in (default: ./backups)")
  .option("--dry-run", "Print the commands without running them")
  .action(async (options: { output?: string; dryRun?: boolean }) => {
    await runBackupCommand({ output: options.output, dryRun: options.dryRun });
  });

program
  .command("restore")
  .description(CLI_COMMAND_DESCRIPTIONS.restore)
  .option("--mongo <file>", "MongoDB archive file (mongodump --archive)")
  .option("--postgres <file>", "PostgreSQL dump file")
  .option(
    "--env <file>",
    "The backup's apps/api/.env (api-env-<stamp>.env): its INSTANCE_SECRET decrypts the saved keys",
  )
  .option(
    "--from <dir>",
    "Restore everything from a backup folder (its newest backup)",
  )
  .option("--dry-run", "Print the commands without running them")
  .action(
    async (options: {
      mongo?: string;
      postgres?: string;
      env?: string;
      from?: string;
      dryRun?: boolean;
    }) => {
      await runRestoreCommand({
        mongo: options.mongo,
        postgres: options.postgres,
        env: options.env,
        from: options.from,
        dryRun: options.dryRun,
      });
    },
  );

program
  .command("init")
  .helpGroup(CONTRIBUTOR_COMMANDS)
  .description(CLI_COMMAND_DESCRIPTIONS.init)
  .option("--branch <branch>", "Git branch to clone")
  .action(async (options: { branch?: string }) => {
    await runInit({ branch: options.branch });
  });

program
  .command("setup")
  .helpGroup(CONTRIBUTOR_COMMANDS)
  .description(CLI_COMMAND_DESCRIPTIONS.setup)
  .action(async () => {
    await runSetup();
  });

program
  .command("dev [profile]")
  .helpGroup(CONTRIBUTOR_COMMANDS)
  .description(CLI_COMMAND_DESCRIPTIONS.dev)
  .action(async (profile?: string) => {
    try {
      await runDev(profile);
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    }
  });
// Before commander: printing the header waits on the instance probe, and
// enablePositionalOptions means --version is only ever the first argument.
if (VERSION_FLAGS.has(process.argv[2] ?? "")) {
  await printVersion();
  process.exit(0);
}

// Show help when no command is given instead of silently running init
if (!process.argv.slice(2).length) {
  program.outputHelp();
  process.exit(0);
}

program.parse();
