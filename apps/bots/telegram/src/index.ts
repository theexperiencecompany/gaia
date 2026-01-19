import { createBot } from "./bot";

let bot: Awaited<ReturnType<typeof createBot>> | null = null;

async function main() {
  bot = await createBot();
}

async function shutdown() {
  console.log("Shutting down Telegram bot...");
  if (bot) {
    await bot.stop();
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
