import { allCommands, runBotProcess } from "@gaia/shared/bots";
import { WhatsAppAdapter } from "./adapter";

runBotProcess(new WhatsAppAdapter(), allCommands);
