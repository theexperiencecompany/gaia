import type { Bot } from "grammy";
import type { GaiaClient } from "@gaia/shared";
import { registerGroupHandler } from "./group";
import { registerMessageHandler } from "./message";

export function registerHandlers(bot: Bot, gaia: GaiaClient) {
  // Group handler must be registered BEFORE private message handler
  // because Grammy processes middleware in order, and the group handler
  // calls next() for non-group messages.
  registerGroupHandler(bot, gaia);
  registerMessageHandler(bot, gaia);
}
