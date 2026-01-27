import { GaiaClient, loadConfig } from "@gaia/shared";
import { TelegramBot } from "./platform";

export async function createBot(): Promise<TelegramBot> {
  const config = loadConfig();
  const gaia = new GaiaClient(
    config.gaiaApiUrl,
    config.gaiaApiKey,
    config.gaiaWebUrl,
  );
  const bot = new TelegramBot(gaia);
  await bot.start();
  return bot;
}
