import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import {
  type ChatInputCommandInteraction,
  MessageFlags,
  SlashCommandBuilder,
} from "discord.js";
import { delay, splitMessageByBreaks } from "../utils/messageUtils";

export const data = new SlashCommandBuilder()
  .setName("chat")
  .setDescription("Chat with GAIA")
  .addStringOption((option) =>
    option
      .setName("message")
      .setDescription("Your message to GAIA")
      .setRequired(true),
  );

/**
 * Executes the /chat slash command.
 * Sends the user's message to GAIA and replies with the response.
 * Handles authentication if the user is not linked.
 *
 * @param {ChatInputCommandInteraction} interaction - The Discord interaction object.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export async function execute(
  interaction: ChatInputCommandInteraction,
  gaia: GaiaClient,
) {
  const message = interaction.options.getString("message", true);
  const userId = interaction.user.id;
  const channelId = interaction.channelId;

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const response = await gaia.chat({
      message,
      platform: "discord",
      platformUserId: userId,
      channelId,
    });

    if (!response.authenticated) {
      const authUrl = gaia.getAuthUrl();
      await interaction.editReply({
        content: `🔗 Link your Discord account to GAIA to chat:\n${authUrl}\n\nSign in to GAIA and connect Discord in Settings → Linked Accounts.`,
      });
      return;
    }

    // Split response by message breaks and send each part separately
    const messageParts = splitMessageByBreaks(response.response);

    for (let i = 0; i < messageParts.length; i++) {
      const truncated = truncateResponse(messageParts[i], "discord");

      if (i === 0) await interaction.editReply({ content: truncated });
      else {
        // Add small delay between messages for natural flow
        await delay(500);
        await interaction.followUp({
          content: truncated,
          flags: MessageFlags.Ephemeral,
        });
      }
    }
  } catch (error) {
    await interaction.editReply({ content: formatError(error) });
  }
}
