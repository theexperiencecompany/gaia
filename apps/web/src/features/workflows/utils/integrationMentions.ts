import type { Integration } from "@/features/integrations/types";
import { extractMentions } from "@/features/integrations/utils/toolMentions";

/**
 * Integrations a user can @-mention in workflow instructions: the ones they can
 * actually use (connected) or that they created themselves.
 */
export const mentionableIntegrations = (
  integrations: Integration[],
): Integration[] =>
  integrations.filter(
    (i) => i.status === "connected" || i.status === "created",
  );

/**
 * Resolve the integration ids referenced by `@<name>` mentions in a prompt.
 * Mentions are stored by display name; this maps them back to ids so the
 * generator (and persisted `selected_integrations`) get canonical ids.
 */
export const mentionedIntegrationIds = (
  prompt: string,
  integrations: Integration[],
): string[] => {
  const mentionable = mentionableIntegrations(integrations);
  const mentioned = new Set(
    extractMentions(
      prompt ?? "",
      mentionable.map((i) => i.name),
    ),
  );
  return mentionable.filter((i) => mentioned.has(i.name)).map((i) => i.id);
};
