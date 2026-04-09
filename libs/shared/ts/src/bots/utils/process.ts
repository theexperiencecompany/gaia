import type { BotCommand, PlatformName } from "../types";
import { createBotLogger } from "./logger";

interface BootableBotAdapter {
  boot: (commands: BotCommand[]) => Promise<void>;
  shutdown: () => Promise<void>;
}

export function runBotProcess(
  platform: PlatformName,
  adapter: BootableBotAdapter,
  commands: BotCommand[],
): void {
  const logger = createBotLogger(platform, "main");

  const shutdown = async () => {
    try {
      logger.info("process_shutdown_signal");
      await adapter.shutdown();
    } catch (err) {
      logger.error("process_shutdown_failed", undefined, err);
    }
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  logger.info("process_boot_start");
  void adapter
    .boot(commands)
    .then(() => {
      logger.info("process_boot_complete");
    })
    .catch((err) => {
      logger.error("process_fatal_error", undefined, err);
      process.exit(1);
    });
}
