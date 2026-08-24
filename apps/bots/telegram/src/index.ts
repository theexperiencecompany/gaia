import { allCommands, runBotProcess } from "@gaia/shared/bots";
import { TelegramAdapter } from "./adapter";

runBotProcess(new TelegramAdapter(), allCommands);
