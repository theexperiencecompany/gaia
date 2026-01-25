import type { GaiaClient } from "@gaia/shared";
import type { Bot } from "grammy";
import { registerAuthCommand } from "./auth";
import { registerChatCommand } from "./chat";
import { registerStartCommand } from "./start";

export function registerCommands(bot: Bot, gaia: GaiaClient) {
  registerStartCommand(bot);
  registerChatCommand(bot, gaia);
  registerAuthCommand(bot, gaia);
}
