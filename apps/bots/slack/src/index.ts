import { allCommands, runBotProcess } from "@gaia/shared";
import { SlackAdapter } from "./adapter";

runBotProcess(new SlackAdapter(), allCommands);
