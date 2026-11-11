import { getMarketplaceIntegration } from "@/features/integrations/lib/serverMarketplaceApi";
import type { CommunityIntegration } from "@/features/integrations/types";
import type { PersonaData } from "./personasData";

/** A persona's relevant integrations (by id) as live marketplace records; throws on an id the marketplace does not serve. */
export async function resolvePersonaIntegrations(
  persona: Pick<PersonaData, "slug" | "relevantIntegrations">,
): Promise<CommunityIntegration[]> {
  return Promise.all(
    persona.relevantIntegrations.map(async (integrationId) => {
      const integration = await getMarketplaceIntegration(integrationId);
      if (!integration) {
        throw new Error(
          `Persona "${persona.slug}" lists integration "${integrationId}", which the marketplace does not serve`,
        );
      }
      return integration;
    }),
  );
}
