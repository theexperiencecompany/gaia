import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { Message } from "discord.js";
import { getRandomGreeting } from "../constants/greetings";

/**
 * Handles messages where the bot is mentioned.
 * Processes the message through GAIA just like the /chat command.
 *
 * @param {Message} message - The Discord message object.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export async function handleMention(message: Message, gaia: GaiaClient) {
  const content = message.content.replace(/<@!?\d+>/g, "").trim();

  if (!content) {
    await message.reply(getRandomGreeting());
    return;
  }

  try {
    if ("sendTyping" in message.channel) await message.channel.sendTyping();

    const response = await gaia.chat({
      message: content,
      platform: "discord",
      platformUserId: message.author.id,
      channelId: message.channelId,
    });

    if (!response.authenticated) {
      const authUrl = gaia.getAuthUrl();
      await message.reply(
        `🔗 Link your Discord account to GAIA to chat:\n${authUrl}\n\nSign in to GAIA and connect Discord in Settings → Linked Accounts.`,
      );
      return;
    }

    const truncated = truncateResponse(response.response, "discord");
    await message.reply(truncated);
  } catch (error) {
    await message.reply(formatError(error));
  }
}
