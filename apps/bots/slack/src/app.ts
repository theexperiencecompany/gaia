import { GaiaClient, loadConfig } from "@gaia/shared";
import { SlackBot } from "./platform";

export async function createApp(): Promise<SlackBot> {
  const config = loadConfig();
  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);
  const bot = new SlackBot(gaia);
  await bot.start();
  return bot;
}
