import type { GaiaClient } from "@gaia/shared";
import type { App } from "@slack/bolt";
import { registerAuthCommand } from "./auth";
import { registerGaiaCommand } from "./gaia";

export function registerCommands(app: App, gaia: GaiaClient) {
  registerGaiaCommand(app, gaia);
  registerAuthCommand(app, gaia);
}
