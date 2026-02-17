import type { Message } from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import { splitMessage, formatError } from "@gaia/shared";

export async function handleMention(
  message: Message,
  gaia: GaiaClient,
  botId: string,
) {
  // Strip only the bot's own mention tag so user references remain intact
  const content = message.content
    .replace(new RegExp(`<@!?${botId}>`, "g"), "")
    .trim();

  if (!content) {
    await message.reply("How can I help you?");
    return;
  }

  try {
    if ("sendTyping" in message.channel) {
      await message.channel.sendTyping();
    }

    const response = await gaia.chat({
      message: content,
      platform: "discord",
      platformUserId: message.author.id,
      channelId: message.channelId,
      publicContext: true,
    });

    if (!response.authenticated) {
      const authUrl = gaia.getAuthUrl("discord", message.author.id);
      await message.reply(
        `Please link your account first: ${authUrl}`,
      );
      return;
    }

    const chunks = splitMessage(response.response, "discord");
    for (const chunk of chunks) {
      await message.reply(chunk);
    }
  } catch (error) {
    await message.reply(formatError(error));
  }
}
