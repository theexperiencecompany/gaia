import type { GaiaClient } from "@gaia/shared";
import type { Message } from "discord.js";

export async function handleMention(message: Message, _gaia: GaiaClient) {
  await message.reply(
    "👋 Hey! Please use the `/chat` command to talk to me.\n\nExample: `/chat message:what's the weather like?`",
  );
}
