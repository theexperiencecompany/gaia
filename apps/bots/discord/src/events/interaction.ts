import type { Interaction, Collection } from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import type { Command } from "../commands";

export async function handleInteraction(
  interaction: Interaction,
  gaia: GaiaClient,
  commands: Collection<string, Command>
) {
  if (!interaction.isChatInputCommand()) return;

  const command = commands.get(interaction.commandName);
  if (!command) {
    console.error(`Unknown command: ${interaction.commandName}`);
    return;
  }

  try {
    await command.execute(interaction, gaia);
  } catch (error) {
    console.error(`Error executing command ${interaction.commandName}:`, error);
    const content = "An error occurred while executing this command.";
    if (interaction.replied || interaction.deferred) {
      await interaction.followUp({ content, ephemeral: true });
    } else {
      await interaction.reply({ content, ephemeral: true });
    }
  }
}
