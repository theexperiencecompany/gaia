import type { GaiaClient } from "@gaia/shared";
import {
  type AutocompleteInteraction,
  type ChatInputCommandInteraction,
  Collection,
  type SlashCommandBuilder,
  type SlashCommandOptionsOnlyBuilder,
  type SlashCommandSubcommandsOnlyBuilder,
} from "discord.js";
import * as chat from "./chat";
import * as help from "./help";
import * as settings from "./settings";

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

const commandModules = [chat, help, settings];

export function registerCommands(): Collection<string, Command> {
  const commands = new Collection<string, Command>();
  for (const cmd of commandModules) {
    commands.set(cmd.data.name, cmd);
  }
  return commands;
}

export function getAllCommands() {
  return commandModules.map((cmd) => cmd.data.toJSON());
}
