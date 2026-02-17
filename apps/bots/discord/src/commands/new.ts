import {
  SlashCommandBuilder,
  ChatInputCommandInteraction,
  MessageFlags,
} from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import { formatError } from "@gaia/shared";

export const data = new SlashCommandBuilder()
  .setName("new")
  .setDescription("Start a new conversation with GAIA");

export async function execute(
  interaction: ChatInputCommandInteraction,
  gaia: GaiaClient,
) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const result = await gaia.newSession(
      "discord",
      interaction.user.id,
      interaction.channelId,
    );
    await interaction.editReply({ content: result.message });
  } catch (error) {
    await interaction.editReply({ content: formatError(error) });
  }
}
