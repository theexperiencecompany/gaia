import type { GaiaClient } from "@gaia/shared";
// import { formatError, truncateResponse } from "@gaia/shared";
import type { Message } from "discord.js";

/**
 * Handles messages where the bot is mentioned.
 * Informs users about available slash commands.
 *
 * @param {Message} message - The Discord message object.
 * @param {GaiaClient} _gaia - The GAIA API client (unused).
 */
export async function handleMention(message: Message, _gaia: GaiaClient) {
  await message.reply(
    "Use `/auth` to link your GAIA account, then `/chat` to chat with me!",
  );

  // TODO: Re-enable public chat when message history is implemented
  // const content = message.content.replace(/<@!?\d+>/g, "").trim();
  //
  // if (!content) {
  //   await message.reply("How can I help you?");
  //   return;
  // }
  //
  // try {
  //   if ("sendTyping" in message.channel) {
  //     await message.channel.sendTyping();
  //   }
  //
  //   const response = await gaia.chatPublic({
  //     message: content,
  //     platform: "discord",
  //     platformUserId: message.author.id,
  //   });
  //
  //   const truncated = truncateResponse(response.response, "discord");
  //   await message.reply(truncated);
  // } catch (error) {
  //   await message.reply(formatError(error));
  // }
}
