import { allCommands, runBotProcess } from "@gaia/shared";
import { WhatsAppAdapter } from "./adapter";

const adapter = new WhatsAppAdapter();

runBotProcess("whatsapp", adapter, allCommands);
