import { allCommands, runBotProcess } from "@gaia/shared/bots";
import { ImessageAdapter } from "./adapter";

runBotProcess(new ImessageAdapter(), allCommands);
