import { loadConfig } from "@gaia/shared";
import { REST, Routes } from "discord.js";
import { getAllCommands } from "./commands";

loadConfig();

const commands = getAllCommands();
const token = process.env.DISCORD_BOT_TOKEN;
const clientId = process.env.DISCORD_CLIENT_ID;

if (!token || !clientId) {
  console.error("Missing DISCORD_BOT_TOKEN or DISCORD_CLIENT_ID");
  process.exit(1);
}

const rest = new REST().setToken(token);

(async () => {
  try {
    console.log(`Registering ${commands.length} slash commands...`);
    await rest.put(Routes.applicationCommands(clientId), { body: commands });
    console.log("Successfully registered slash commands");
  } catch (error) {
    console.error("Failed to register commands:", error);
    process.exit(1);
  }
})();
