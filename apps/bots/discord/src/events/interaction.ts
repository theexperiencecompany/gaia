import type { GaiaClient } from "@gaia/shared";
import { type Collection, type Interaction, MessageFlags } from "discord.js";
import type { Command } from "../commands";

export async function handleInteraction(
  interaction: Interaction,
  gaia: GaiaClient,
  commands: Collection<string, Command>,
) {
  if (interaction.isAutocomplete()) {
    const command = commands.get(interaction.commandName);
    if (command?.autocomplete) {
      try {
        await command.autocomplete(interaction);
      } catch (error) {
        console.error(
          `Autocomplete error for ${interaction.commandName}:`,
          error,
        );
      }
    }
    return;
  }

  if (!interaction.isChatInputCommand()) return;

  const command = commands.get(interaction.commandName);
  if (!command) {
    console.error(`Unknown command: ${interaction.commandName}`);
    await interaction.reply({
      content: `Unknown command: \`/${interaction.commandName}\`. This command may have been removed or is not available.`,
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  try {
    await command.execute(interaction, gaia);
  } catch (error) {
    console.error(`Error executing command ${interaction.commandName}:`);
    console.error(error);

    const errorMessage = error instanceof Error ? error.message : String(error);
    const content = `An error occurred: ${errorMessage}`;

    if (interaction.replied || interaction.deferred) {
      await interaction.followUp({ content, flags: MessageFlags.Ephemeral });
    } else {
      await interaction.reply({ content, flags: MessageFlags.Ephemeral });
    }
  }
}
