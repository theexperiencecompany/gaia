import { allCommands, runBotProcess } from "@gaia/shared";
import { WhatsAppAdapter } from "./adapter";

runBotProcess(new WhatsAppAdapter(), allCommands);
