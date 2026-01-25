import type { GaiaClient } from "@gaia/shared";
import type { Message } from "discord.js";

/**
 * Handles messages where the bot is mentioned.
 * Directs users to use the /chat command instead.
 *
 * @param {Message} message - The Discord message object.
 * @param {GaiaClient} _gaia - The GAIA API client (unused).
 */
export async function handleMention(message: Message, _gaia: GaiaClient) {
  await message.reply(
    "👋 Hey! Please use the `/chat` command to talk to me.\n\nExample: `/chat message:what's the weather like?`",
  );
}
