import {
  Collection,
  SlashCommandBuilder,
  ChatInputCommandInteraction,
  SlashCommandOptionsOnlyBuilder,
  SlashCommandSubcommandsOnlyBuilder,
} from "discord.js";
import type { GaiaClient } from "@gaia/shared";
import * as gaia from "./gaia";
import * as auth from "./auth";
import * as newCmd from "./new";
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
}

export function registerCommands(): Collection<string, Command> {
  const commands = new Collection<string, Command>();
  commands.set(gaia.data.name, gaia);
  commands.set(auth.data.name, auth);
  commands.set(newCmd.data.name, newCmd);
  commands.set(help.data.name, help);
  return commands;
}
