import { allCommands } from "@gaia/shared";
import { WhatsAppAdapter } from "./adapter";

const adapter = new WhatsAppAdapter();

async function main() {
  await adapter.boot(allCommands);
}

async function shutdown() {
  try {
    await adapter.shutdown();
  } catch (err) {
    console.error("Shutdown error:", err);
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

try {
  await main();
} catch (err) {
  console.error("Fatal error:", err);
  process.exit(1);
}
