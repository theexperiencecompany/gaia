import { allCommands, runBotProcess } from "@gaia/shared/bots";
import { DiscordAdapter } from "./adapter";

runBotProcess(new DiscordAdapter(), allCommands);
