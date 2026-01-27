import { createBot } from "./bot";

let client: Awaited<ReturnType<typeof createBot>> | null = null;

async function main() {
  client = await createBot();
}

async function shutdown() {
  console.log("Shutting down Discord bot...");
  if (client) {
    client.destroy();
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
