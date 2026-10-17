/** What each `gaia` command does, in words a first-time self-hoster reads. */
export const CLI_COMMAND_DESCRIPTIONS = {
  up: "Install GAIA and start it (or resume an earlier run)",
  status: "Show whether GAIA is running and healthy",
  stop: "Stop GAIA (your data is kept)",
  start: "Start GAIA again after 'gaia stop'",
  update: "Move GAIA to a newer release (keeps your data and settings)",
  doctor: "Find problems with your install and how to fix them",
  logs: "Show GAIA's logs as they happen",
  bots: "Connect GAIA to Telegram, Discord or Slack",
  connect: "Import browser logins so GAIA's browser stays signed in",
  bridge: "Let GAIA use tools and files on this computer",
  backup: "Save GAIA's data and settings to a folder",
  restore: "Bring back GAIA's data and settings from a backup",
  init: "Set up a development copy of GAIA from scratch",
  setup: "Configure an existing development copy",
  dev: "Run GAIA from source with live reload",
} as const;

/** The canonical way to install the `gaia` CLI, per package manager. */
export const CLI_INSTALL_COMMANDS = {
  npm: "npm install -g @heygaia/cli",
  pnpm: "pnpm add -g @heygaia/cli",
  bun: "bun add -g @heygaia/cli",
} as const;
