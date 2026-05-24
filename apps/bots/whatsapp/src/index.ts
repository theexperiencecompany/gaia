import { allCommands, createBotLogger } from "@gaia/shared";
import { WhatsAppAdapter } from "./adapter";

const adapter = new WhatsAppAdapter();
const logger = createBotLogger("whatsapp", "main");

async function main() {
  logger.info("process_boot_start");
  await adapter.boot(allCommands);
  logger.info("process_boot_complete");
}

async function shutdown() {
  try {
    logger.info("process_shutdown_signal");
    await adapter.shutdown();
  } catch (err) {
    logger.error("process_shutdown_failed", undefined, err);
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

try {
  await main();
} catch (err) {
  logger.error("process_fatal_error", undefined, err);
  process.exit(1);
}
