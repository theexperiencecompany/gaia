import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";
import { registerGaiaCommand } from "./gaia";
import { registerAuthCommand } from "./auth";
import { registerNewCommand } from "./new";
import { registerHelpCommand } from "./help";

export function registerCommands(app: App, gaia: GaiaClient) {
  registerGaiaCommand(app, gaia);
  registerAuthCommand(app, gaia);
  registerNewCommand(app, gaia);
  registerHelpCommand(app);
}
