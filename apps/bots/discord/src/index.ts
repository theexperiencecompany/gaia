import { allCommands, runBot } from "@gaia/shared";
import { DiscordAdapter } from "./adapter";

runBot(new DiscordAdapter(), allCommands);
