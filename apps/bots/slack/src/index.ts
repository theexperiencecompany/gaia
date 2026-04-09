import { allCommands, runBotProcess } from "@gaia/shared";
import { SlackAdapter } from "./adapter";

const adapter = new SlackAdapter();

runBotProcess("slack", adapter, allCommands);
