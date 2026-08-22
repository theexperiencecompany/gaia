export const CLI_COMMAND_DESCRIPTIONS = {
  init: "Full setup from scratch (clone, configure, start)",
  setup: "Configure an existing GAIA repository",
  status: "Check health of all GAIA services",
  start: "Start GAIA services (self-host mode)",
  dev: "Run developer mode in Nx TUI (`gaia dev` or `gaia dev full`)",
  logs: "Stream logs for running GAIA services",
  stop: "Stop all GAIA services (safe mode by default)",
  up: "One-command setup: configure, pull and start GAIA (self-host)",
  doctor: "Diagnose a GAIA install: docker, services and setup checks",
} as const;

export const REQUIRED_DOC_COMMANDS = [
  "gaia init",
  "gaia setup",
  "gaia start",
  "gaia dev",
  "gaia dev full",
  "gaia logs",
  "gaia stop",
  "gaia status",
  "gaia up",
  "gaia doctor",
] as const;

export const REQUIRED_INSTALL_COMMANDS = [
  "npm install -g @heygaia/cli",
  "pnpm add -g @heygaia/cli",
  "bun add -g @heygaia/cli",
] as const;
