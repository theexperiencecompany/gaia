import { GaiaClient, loadConfig } from "@gaia/shared";
import { DiscordBot } from "./platform";

export async function createBot(): Promise<DiscordBot> {
  const config = loadConfig();
  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);
  const bot = new DiscordBot(gaia);
  await bot.start();
  return bot;
}
