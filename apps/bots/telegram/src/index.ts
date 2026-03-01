import { allCommands, runBot } from "@gaia/shared";
import { TelegramAdapter } from "./adapter";

runBot(new TelegramAdapter(), allCommands);
