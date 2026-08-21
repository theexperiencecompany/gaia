import { allCommands, runBotProcess } from "@gaia/shared";
import { ImessageAdapter } from "./adapter";

runBotProcess(new ImessageAdapter(), allCommands);
