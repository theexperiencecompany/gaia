import type { GaiaClient } from "@gaia/shared";
import {
  type AutocompleteInteraction,
  type ChatInputCommandInteraction,
  Collection,
  type SlashCommandBuilder,
  type SlashCommandOptionsOnlyBuilder,
  type SlashCommandSubcommandsOnlyBuilder,
} from "discord.js";
import * as auth from "./auth";
import * as gaia from "./gaia";
import * as help from "./help";

export interface Command {
  data:
    | SlashCommandBuilder
    | SlashCommandOptionsOnlyBuilder
    | SlashCommandSubcommandsOnlyBuilder;
  execute: (
    interaction: ChatInputCommandInteraction,
    client: GaiaClient,
  ) => Promise<void>;
  autocomplete?: (interaction: AutocompleteInteraction) => Promise<void>;
}

const commandModules = [gaia, auth, help];

export function registerCommands(): Collection<string, Command> {
  const commands = new Collection<string, Command>();
  for (const cmd of commandModules) {
    commands.set(cmd.data.name, cmd);
  }
  return commands;
}

/**
 * Returns all command data as JSON for Discord API registration.
 * Used by deploy-commands.ts to register slash commands.
 */
export function getAllCommands() {
  return commandModules.map((cmd) => cmd.data.toJSON());
}
