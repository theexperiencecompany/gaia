import type { GaiaClient } from "@gaia/shared";
import type { Bot } from "grammy";
import { registerAuthCommand } from "./auth";
import { registerGaiaCommand } from "./gaia";
import { registerStartCommand } from "./start";

export function registerCommands(bot: Bot, gaia: GaiaClient) {
  registerStartCommand(bot);
  registerGaiaCommand(bot, gaia);
  registerAuthCommand(bot, gaia);
}
