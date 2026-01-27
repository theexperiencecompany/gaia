import { SlashCommandBuilder, ChatInputCommandInteraction, MessageFlags } from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import { truncateResponse, formatError } from "@gaia/shared";

export const data = new SlashCommandBuilder()
  .setName("gaia")
  .setDescription("Chat with GAIA")
  .addStringOption((option) =>
    option
      .setName("message")
      .setDescription("Your message to GAIA")
      .setRequired(true)
  );

/**
 * Executes the /gaia slash command.
 * Sends the user's message to GAIA and replies with the response.
 * Handles authentication if the user is not linked.
 *
 * @param {ChatInputCommandInteraction} interaction - The Discord interaction object.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export async function execute(
  interaction: ChatInputCommandInteraction,
  gaia: GaiaClient
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
      channelId
    });

    if (!response.authenticated) {
      const authUrl = gaia.getAuthUrl("discord", userId);
      await interaction.editReply({
        content: `Please authenticate first: ${authUrl}`
      });
      return;
    }

    const truncated = truncateResponse(response.response, "discord");
    await interaction.editReply({ content: truncated });
  } catch (error) {
    await interaction.editReply({ content: formatError(error) });
  }
}
