import { SlashCommandBuilder, ChatInputCommandInteraction, MessageFlags } from "discord.js";
import type { GaiaClient } from "@gaia/shared";

/**
 * Slash command definition for /auth.
 */
export const data = new SlashCommandBuilder()
  .setName("auth")
  .setDescription("Link your Discord account to GAIA");

/**
 * Executes the /auth slash command.
 * Provides a link for the user to authenticate with GAIA.
 *
 * @param {ChatInputCommandInteraction} interaction - The Discord interaction object.
 * @param {GaiaClient} gaia - The GAIA API client.
 */
export async function execute(
  interaction: ChatInputCommandInteraction,
  gaia: GaiaClient
) {
  const userId = interaction.user.id;
  const authUrl = gaia.getAuthUrl("discord", userId);

  await interaction.reply({
    content: `Click to link your Discord account to GAIA: ${authUrl}`,
    flags: MessageFlags.Ephemeral
  });
}
