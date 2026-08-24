import { allCommands, runBotProcess } from "@gaia/shared/bots";
import { SlackAdapter } from "./adapter";

runBotProcess(new SlackAdapter(), allCommands);
