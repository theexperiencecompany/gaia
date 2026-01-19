import type { Message } from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import { truncateResponse, formatError } from "@gaia/shared";

/**
 * Handles messages where the bot is mentioned.
 * Treats these as public (unauthenticated) chat requests.
 *
 * @param {Message} message - The Discord message object.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export async function handleMention(message: Message, gaia: GaiaClient) {
  const content = message.content.replace(/<@!?\d+>/g, "").trim();

  if (!content) {
    await message.reply("How can I help you?");
    return;
  }

  try {
    if ('sendTyping' in message.channel) {
      await message.channel.sendTyping();
    }

    const response = await gaia.chatPublic({
      message: content,
      platform: "discord",
      platformUserId: message.author.id
    });

    const truncated = truncateResponse(response.response, "discord");
    await message.reply(truncated);
  } catch (error) {
    await message.reply(formatError(error));
  }
}
