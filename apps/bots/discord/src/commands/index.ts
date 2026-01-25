import type { GaiaClient } from "@gaia/shared";
import {
  type ChatInputCommandInteraction,
  Collection,
  type SlashCommandBuilder,
  type SlashCommandOptionsOnlyBuilder,
  type SlashCommandSubcommandsOnlyBuilder,
} from "discord.js";
import * as auth from "./auth";
import * as gaia from "./gaia";

export interface Command {
  data:
    | SlashCommandBuilder
    | SlashCommandOptionsOnlyBuilder
    | SlashCommandSubcommandsOnlyBuilder;
  execute: (
    interaction: ChatInputCommandInteraction,
    client: GaiaClient,
  ) => Promise<void>;
}

export function registerCommands(): Collection<string, Command> {
  const commands = new Collection<string, Command>();
  commands.set(gaia.data.name, gaia);
  commands.set(auth.data.name, auth);
  return commands;
}
