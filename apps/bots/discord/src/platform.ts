import type { GaiaClient, Platform, PlatformBot } from "@gaia/shared";
import {
  Client,
  Collection,
  Events,
  GatewayIntentBits,
  REST,
  Routes,
} from "discord.js";
import type { Command } from "./commands";
import { getAllCommands, registerCommands } from "./commands";
import { handleInteraction } from "./events/interaction";
import { handleMention } from "./events/mention";

export class DiscordBot implements PlatformBot {
  readonly platform: Platform = "discord";
  private client: Client;
  private gaia: GaiaClient;
  private commands: Collection<string, Command>;
  private token: string;
  private clientId?: string;
  private guildId?: string;

  constructor(gaia: GaiaClient) {
    const token = process.env.DISCORD_BOT_TOKEN;
    if (!token) {
      throw new Error("DISCORD_BOT_TOKEN is required");
    }

    this.token = token;
    this.clientId = process.env.DISCORD_CLIENT_ID;
    this.guildId = process.env.DISCORD_GUILD_ID;
    this.gaia = gaia;
    this.commands = new Collection();

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
      ],
    });

    this.setupEventHandlers();
  }

  async start(): Promise<void> {
    this.commands = registerCommands();
    await this.client.login(this.token);
  }

  async stop(): Promise<void> {
    this.client.destroy();
  }

  private setupEventHandlers(): void {
    this.client.once(Events.ClientReady, async (c) => {
      console.log(`Discord bot ready as ${c.user.tag}`);
      await this.deployCommands();
    });

    this.client.on(Events.InteractionCreate, async (interaction) => {
      await handleInteraction(interaction, this.gaia, this.commands);
    });

    this.client.on(Events.MessageCreate, async (message) => {
      if (message.author.bot) return;
      if (!this.client.user) return;
      if (!message.mentions.has(this.client.user)) return;
      await handleMention(message, this.gaia);
    });
  }

  private async deployCommands(): Promise<void> {
    if (!this.clientId) return;

    try {
      const rest = new REST().setToken(this.token);
      const commands = getAllCommands();
      const route = this.guildId
        ? Routes.applicationGuildCommands(this.clientId, this.guildId)
        : Routes.applicationCommands(this.clientId);

      await rest.put(route, { body: commands });
      const scope = this.guildId ? `guild ${this.guildId}` : "globally";
      console.log(`Registered ${commands.length} slash commands ${scope}`);
    } catch (error) {
      console.error("Failed to deploy slash commands:", error);
    }
  }
}
