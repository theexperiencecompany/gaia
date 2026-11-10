import { getMarketplaceIntegration } from "@/features/integrations/lib/serverMarketplaceApi";
import type { CommunityIntegration } from "@/features/integrations/types";
import type { PersonaData } from "./personasData";

/** A persona's relevant integrations as live marketplace records; throws on a slug the marketplace does not serve. */
export async function resolvePersonaIntegrations(
  persona: Pick<PersonaData, "slug" | "relevantIntegrations">,
): Promise<CommunityIntegration[]> {
  return Promise.all(
    persona.relevantIntegrations.map(async (slug) => {
      const integration = await getMarketplaceIntegration(slug);
      if (!integration) {
        throw new Error(
          `Persona "${persona.slug}" lists integration "${slug}", which is not a marketplace slug`,
        );
      }
      return integration;
    }),
  );
}
