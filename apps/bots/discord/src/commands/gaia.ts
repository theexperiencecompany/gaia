import {
  SlashCommandBuilder,
  ChatInputCommandInteraction,
  MessageFlags,
} from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import { splitMessage, formatError } from "@gaia/shared";

export const data = new SlashCommandBuilder()
  .setName("gaia")
  .setDescription("Chat with GAIA")
  .addStringOption((option) =>
    option
      .setName("message")
      .setDescription("Your message to GAIA")
      .setRequired(true),
  );

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
      const authUrl = gaia.getAuthUrl("discord", userId);
      await interaction.editReply({
        content: `Please authenticate first: ${authUrl}`,
      });
      return;
    }

    const chunks = splitMessage(response.response, "discord");
    await interaction.editReply({ content: chunks[0] });
    for (let i = 1; i < chunks.length; i++) {
      await interaction.followUp({
        content: chunks[i],
        flags: MessageFlags.Ephemeral,
      });
    }
  } catch (error) {
    await interaction.editReply({ content: formatError(error) });
  }
}
