import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";
import { registerGaiaCommand } from "./gaia";
import { registerAuthCommand } from "./auth";

export function registerCommands(app: App, gaia: GaiaClient) {
  registerGaiaCommand(app, gaia);
  registerAuthCommand(app, gaia);
}
