import { createApp } from "./app";

let app: Awaited<ReturnType<typeof createApp>> | null = null;

async function main() {
  app = await createApp();
}

async function shutdown() {
  console.log("Shutting down Slack bot...");
  if (app) {
    await app.stop();
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
