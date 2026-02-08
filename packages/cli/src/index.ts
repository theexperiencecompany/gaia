#!/usr/bin/env bun

import { Command } from "commander";
import { runInit } from "./commands/init/handler.js";

const program = new Command();

program
  .name("gaia")
  .description("CLI tool for setting up and managing GAIA")
  .version("0.1.0");

program
  .command("init")
  .description("Full setup from scratch (clone, configure, start)")
  .action(async () => {
    await runInit();
  });

program
  .command("setup")
  .description("Configure an existing GAIA repository")
  .action(async () => {
    const { runSetup } = await import("./commands/setup/handler.js");
    await runSetup();
  });

program
  .command("status")
  .description("Check health of all GAIA services")
  .action(async () => {
    const { runStatus } = await import("./commands/status/handler.js");
    await runStatus();
  });

program
  .command("start")
  .description("Start GAIA services")
  .action(async () => {
    const { runStart } = await import("./commands/start/handler.js");
    await runStart();
  });

program
  .command("stop")
  .description("Stop all GAIA services")
  .action(async () => {
    const { runStop } = await import("./commands/stop/handler.js");
    await runStop();
  });

// Default to init when no command given
program.action(async () => {
  await runInit();
});

program.parse();
