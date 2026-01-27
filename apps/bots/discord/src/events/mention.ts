import type { Message } from "discord.js";

export async function handleMention(message: Message) {
  try {
    await message.reply(
      "👋 Hey! Use `/chat` to talk to me privately, or @mention me with a message!",
    );
  } catch (error) {
    console.error("Failed to send mention reply:", error);
  }
}
