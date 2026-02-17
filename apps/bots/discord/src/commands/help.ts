import {
  SlashCommandBuilder,
  ChatInputCommandInteraction,
  MessageFlags,
} from "discord.js";
import type { GaiaClient } from "@gaia/shared";

export const data = new SlashCommandBuilder()
  .setName("help")
  .setDescription("Show available GAIA commands");

export async function execute(
  interaction: ChatInputCommandInteraction,
  _gaia: GaiaClient,
) {
  await interaction.reply({
    content:
      "**GAIA Commands**\n\n" +
      "`/gaia <message>` — Chat with GAIA\n" +
      "`/auth` — Link your Discord account\n" +
      "`/new` — Start a new conversation\n" +
      "`/help` — Show this help message\n\n" +
      "You can also @mention GAIA in any channel.",
    flags: MessageFlags.Ephemeral,
  });
}
