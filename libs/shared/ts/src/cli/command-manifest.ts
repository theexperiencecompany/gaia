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
  backup: "Back up GAIA databases (MongoDB + PostgreSQL) to a local directory",
  restore: "Restore GAIA databases from backup files",
  update: "Pull latest changes and restart services (preserves .env and volumes)",
} as const;

/** The canonical way to install the `gaia` CLI, per package manager. */
export const CLI_INSTALL_COMMANDS = {
  npm: "npm install -g @heygaia/cli",
  pnpm: "pnpm add -g @heygaia/cli",
  bun: "bun add -g @heygaia/cli",
} as const;
