import { allCommands, runBotProcess } from "@gaia/shared";
import { DiscordAdapter } from "./adapter";

const adapter = new DiscordAdapter();

runBotProcess("discord", adapter, allCommands);
