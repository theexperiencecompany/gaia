import { allCommands, runBotProcess } from "@gaia/shared";
import { TelegramAdapter } from "./adapter";

const adapter = new TelegramAdapter();

runBotProcess("telegram", adapter, allCommands);
