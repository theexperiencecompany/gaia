import { allCommands, runBotProcess } from "@gaia/shared";
import { DiscordAdapter } from "./adapter";

runBotProcess(new DiscordAdapter(), allCommands);
