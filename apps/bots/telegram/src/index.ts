import { allCommands, runBotProcess } from "@gaia/shared";
import { TelegramAdapter } from "./adapter";

runBotProcess(new TelegramAdapter(), allCommands);
