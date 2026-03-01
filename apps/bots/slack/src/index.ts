import { allCommands, runBot } from "@gaia/shared";
import { SlackAdapter } from "./adapter";

runBot(new SlackAdapter(), allCommands);
