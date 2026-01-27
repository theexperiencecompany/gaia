import type { GaiaClient } from "@gaia/shared";
import { formatError, truncateResponse } from "@gaia/shared";
import {
  type ChatInputCommandInteraction,
  MessageFlags,
  SlashCommandBuilder,
} from "discord.js";

export const data = new SlashCommandBuilder()
  .setName("chat")
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
      const authUrl = gaia.getAuthUrl();
      await interaction.editReply({
        content: `🔗 Link your Discord account to GAIA to chat:\n${authUrl}\n\nSign in to GAIA and connect Discord in Settings → Linked Accounts.`,
      });
      return;
    }

    const truncated = truncateResponse(response.response, "discord");
    await interaction.editReply({ content: truncated });
  } catch (error) {
    await interaction.editReply({ content: formatError(error) });
  }
}
