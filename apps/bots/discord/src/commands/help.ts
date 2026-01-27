import type { GaiaClient } from "@gaia/shared";
import {
  type ChatInputCommandInteraction,
  EmbedBuilder,
  SlashCommandBuilder,
} from "discord.js";

export const data = new SlashCommandBuilder()
  .setName("help")
  .setDescription("Learn how to use GAIA");

export async function execute(
  interaction: ChatInputCommandInteraction,
  _gaia: GaiaClient,
) {
  const embed = new EmbedBuilder()
    .setTitle("GAIA - Your Personal AI Assistant")
    .setDescription(
      "GAIA helps you manage tasks, emails, calendar, and more. Here's how to interact with me:",
    )
    .setColor(0x7c3aed)
    .addFields(
      {
        name: "📝 Slash Commands",
        value: [
          "`/chat <message>` - Chat with GAIA privately (ephemeral)",
          "`/settings` - View your account and connected integrations",
          "`/help` - Show this help message",
        ].join("\n"),
      },
      {
        name: "💬 Mentions",
        value: "Mention me to see available commands and get started!",
      },
      {
        name: "🔗 Account Linking",
        value:
          "To use GAIA with your personal data (calendar, tasks, emails), sign in at [heygaia.io](https://heygaia.io) and link Discord in Settings → Linked Accounts.",
      },
      {
        name: "🌐 Links",
        value: [
          "[Website](https://heygaia.io)",
          "[GitHub](https://github.com/heygaia/gaia)",
          "[Documentation](https://docs.heygaia.io)",
        ].join(" • "),
      },
    )
    .setFooter({ text: "GAIA - General AI Assistant" })
    .setTimestamp();

  await interaction.reply({ embeds: [embed] });
}
