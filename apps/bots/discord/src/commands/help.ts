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
          "`/gaia <message>` - Chat with GAIA privately (ephemeral)",
          "`/auth` - Link your Discord account to GAIA",
          "`/help` - Show this help message",
        ].join("\n"),
      },
      {
        name: "💬 Mentions",
        value:
          "You can also @mention me in any channel to chat publicly. This is great for quick questions or when you want others to see the conversation.",
      },
      {
        name: "🔗 Account Linking",
        value:
          "Use `/auth` to link your Discord account with GAIA. This enables personalized features like accessing your calendar, tasks, and integrations.",
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
