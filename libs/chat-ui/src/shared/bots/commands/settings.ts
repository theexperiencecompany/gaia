/**
 * Unified `/settings` command — displays the user's GAIA account settings.
 *
 * Shows account info, selected AI model, and connected integrations
 * using a {@link RichMessage}. If the user isn't authenticated, shows
 * an auth link instead.
 *
 * @module
 */

import type { BotCommand, CommandExecuteParams, RichMessage } from "../types";
import { formatBotError } from "../utils/formatters";

/**
 * Converts a potentially relative URL to an absolute one using the frontend base URL.
 *
 * @param url - The URL to convert (may be relative, absolute, or null).
 * @param frontendUrl - The GAIA frontend base URL.
 * @returns An absolute URL string, or `null` if the input was falsy.
 */
function toAbsoluteUrl(
  url: string | null | undefined,
  frontendUrl: string,
): string | null {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return `${frontendUrl}${url.startsWith("/") ? "" : "/"}${url}`;
}

/** `/settings` command definition. */
export const settingsCommand: BotCommand = {
  name: "settings",
  description: "View your GAIA account settings and connected integrations",

  async execute({ gaia, target, ctx }: CommandExecuteParams): Promise<void> {
    try {
      const settings = await gaia.getSettings(ctx.platform, ctx.platformUserId);

      if (!settings.authenticated) {
        try {
          const { authUrl } = await gaia.createLinkToken(
            ctx.platform,
            ctx.platformUserId,
          );
          await target.sendEphemeral(
            "❌ Not linked yet.\n\n" +
              "🔗 Link your account to GAIA to view settings:\n" +
              `${authUrl}\n\n` +
              "Sign in to GAIA and connect your account in Settings → Linked Accounts.",
          );
        } catch {
          await target.sendEphemeral(
            "❌ Not linked yet. Use /auth to link your account.",
          );
        }
        return;
      }

      const frontendUrl = gaia.getFrontendUrl();

      let accountAge = "Unknown";
      if (settings.accountCreatedAt) {
        const createdDate = new Date(settings.accountCreatedAt);
        accountAge = createdDate.toLocaleDateString("en-US", {
          year: "numeric",
          month: "long",
          day: "numeric",
        });
      }

      let integrationsText = "None connected";
      if (settings.connectedIntegrations.length > 0) {
        integrationsText = settings.connectedIntegrations
          .map((i) => {
            const statusDot = i.status === "connected" ? "🟢" : "🟠";
            return `${statusDot} ${i.name}`;
          })
          .join("\n");
      }

      const profileImageUrl = toAbsoluteUrl(
        settings.profileImageUrl,
        frontendUrl,
      );

      const richMsg: RichMessage = {
        type: "embed",
        title: "⚙️ Your GAIA Settings",
        color: 0x7c3aed,
        fields: [
          {
            name: "👤 Account",
            value: [
              `**Name:** ${settings.userName || "Not set"}`,
              `**Member since:** ${accountAge}`,
            ].join("\n"),
          },
          {
            name: "🔗 Connected Integrations",
            value: integrationsText,
          },
        ],
        footer: "Manage settings at heygaia.io/settings",
        timestamp: true,
        thumbnailUrl: profileImageUrl ?? undefined,
        authorName: profileImageUrl
          ? settings.userName || "GAIA User"
          : undefined,
        authorIconUrl: profileImageUrl ?? undefined,
      };

      await target.sendRich(richMsg);
    } catch (error) {
      await target.sendEphemeral(formatBotError(error));
    }
  },
};
