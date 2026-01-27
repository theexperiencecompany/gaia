import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { registerStartCommand } from "./start";
import { registerGaiaCommand } from "./gaia";
import { registerAuthCommand } from "./auth";

export function registerCommands(bot: Bot, gaia: GaiaClient) {
  registerStartCommand(bot);
  registerGaiaCommand(bot, gaia);
  registerAuthCommand(bot, gaia);
}
