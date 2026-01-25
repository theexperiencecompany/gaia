import type { GaiaClient } from "@gaia/shared";
import type { Bot } from "grammy";
import { registerMessageHandler } from "./message";

export function registerHandlers(bot: Bot, gaia: GaiaClient) {
  registerMessageHandler(bot, gaia);
}
