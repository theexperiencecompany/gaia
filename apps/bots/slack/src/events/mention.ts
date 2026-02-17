import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";
import { splitMessage, formatError, UserRateLimiter } from "@gaia/shared";

const rateLimiter = new UserRateLimiter(20, 60_000);

export function registerMentionEvent(app: App, gaia: GaiaClient) {
  app.event("app_mention", async ({ event, say, client, context }) => {
    // Strip only the bot's own mention tag so user references remain intact
    const botMention = context.botUserId
      ? new RegExp(`<@${context.botUserId}>`, "g")
      : null;
    const content = botMention
      ? event.text.replace(botMention, "").trim()
      : event.text.trim();
    const userId = event.user;

    if (!userId) return;

    if (!rateLimiter.check(userId)) {
      await say("You're sending messages too fast. Please slow down.");
      return;
    }

    if (!content) {
      await say("How can I help you?");
      return;
    }

    // Post a "thinking" message
    let thinkingTs: string | undefined;
    try {
      const thinkingMsg = await client.chat.postMessage({
        channel: event.channel,
        text: "Thinking...",
      });
      thinkingTs = thinkingMsg.ts;
    } catch {
      // If posting fails, continue without typing indicator
    }

    try {
      const response = await gaia.chat({
        message: content,
        platform: "slack",
        platformUserId: userId,
        channelId: event.channel,
        publicContext: true,
      });

      if (!response.authenticated) {
        const authUrl = gaia.getAuthUrl("slack", userId);
        const text = `Please link your account first: ${authUrl}`;
        if (thinkingTs) {
          await client.chat.update({
            channel: event.channel,
            ts: thinkingTs,
            text,
          });
        } else {
          await say(text);
        }
        return;
      }

      const chunks = splitMessage(response.response, "slack");

      // Update thinking message with first chunk
      if (thinkingTs) {
        await client.chat.update({
          channel: event.channel,
          ts: thinkingTs,
          text: chunks[0],
        });
      } else {
        await say(chunks[0]);
      }

      // Send remaining chunks
      for (let i = 1; i < chunks.length; i++) {
        await say(chunks[i]);
      }
    } catch (error) {
      const errorText = formatError(error);
      if (thinkingTs) {
        await client.chat.update({
          channel: event.channel,
          ts: thinkingTs,
          text: errorText,
        });
      } else {
        await say(errorText);
      }
    }
  });
}
