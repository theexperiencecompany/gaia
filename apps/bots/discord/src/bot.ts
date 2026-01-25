import { GaiaClient, loadConfig } from "@gaia/shared";
import { Client, Events, GatewayIntentBits, REST, Routes } from "discord.js";
import { getAllCommands, registerCommands } from "./commands";
import { handleInteraction } from "./events/interaction";
import { handleMention } from "./events/mention";

async function deployCommands(
  token: string,
  clientId: string,
  guildId?: string,
) {
  const rest = new REST().setToken(token);
  const commands = getAllCommands();
  const route = guildId
    ? Routes.applicationGuildCommands(clientId, guildId)
    : Routes.applicationCommands(clientId);
  await rest.put(route, { body: commands });
  return { count: commands.length, isGuild: !!guildId };
}

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
  const clientId = process.env.DISCORD_CLIENT_ID;
  const guildId = process.env.DISCORD_GUILD_ID;

  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is required");
  }

  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
    ],
  });

  const gaia = new GaiaClient(config.gaiaApiUrl, config.gaiaApiKey);
  const commands = registerCommands();

  client.once(Events.ClientReady, async (c) => {
    console.log(`Discord bot ready as ${c.user.tag}`);
    if (clientId) {
      try {
        const { count, isGuild } = await deployCommands(
          token,
          clientId,
          guildId,
        );
        const scope = isGuild ? `guild ${guildId}` : "globally";
        console.log(`Registered ${count} slash commands ${scope}`);
      } catch (error) {
        console.error("Failed to deploy slash commands:", error);
      }
    }
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
