import { Client, GatewayIntentBits, Events } from "discord.js";
import { GaiaClient, loadConfig } from "@gaia/shared";
import { registerCommands } from "./commands";
import { handleMention } from "./events/mention";
import { handleInteraction } from "./events/interaction";

/**
 * Initializes and starts the Discord bot.
 * Sets up client intents, commands, and event listeners.
 *
 * @returns {Promise<Client>} The initialized Discord client instance.
 * @throws {Error} If DISCORD_BOT_TOKEN is missing in environment variables.
 */
export async function createBot() {
  const config = loadConfig();
  const token = process.env.DISCORD_BOT_TOKEN;

  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is required");
  }

  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent
    ]
  });

  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);
  const commands = registerCommands();

  client.once(Events.ClientReady, (c) => {
    console.log(`Discord bot ready as ${c.user.tag}`);
  });

  client.on(Events.InteractionCreate, async (interaction) => {
    await handleInteraction(interaction, gaia, commands);
  });

  client.on(Events.MessageCreate, async (message) => {
    if (message.author.bot) return;
    if (!client.user) return;
    if (!message.mentions.has(client.user)) return;
    await handleMention(message, gaia);
  });

  await client.login(token);
  return client;
}
