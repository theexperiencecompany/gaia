import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import type { Message } from "discord.js";

export async function handleMention(message: Message, gaia: GaiaClient) {
  const content = message.content.replace(/<@!?\d+>/g, "").trim();

  if (!content) {
    await message.reply(
      "👋 Hey! Use `/chat` to talk to me privately, or @mention me with a message!",
    );
    return;
  }

  try {
    const response = await gaia.chatPublic({
      message: content,
      platform: "discord",
      platformUserId: message.author.id,
    });

    const truncated = truncateResponse(response.response, "discord");
    await message.reply(truncated);
  } catch (error) {
    await message.reply(formatError(error));
  }
}
