import type { GaiaClient } from "@gaia/shared";
import type { App } from "@slack/bolt";
import { registerAuthCommand } from "./auth";
import { registerChatCommand } from "./chat";

export function registerCommands(app: App, gaia: GaiaClient) {
  registerChatCommand(app, gaia);
  registerAuthCommand(app, gaia);
}
