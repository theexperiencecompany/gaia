import type { CommunityIntegration } from "../types";
import { IntegrationChipLink } from "./IntegrationChipLink";

interface IntegrationRelatedIntegrationsProps {
  /** Server-picked by relatedIntegrations, so the links are in the SSR HTML. */
  readonly integrations: readonly CommunityIntegration[];
}

/** "Related integrations" on a marketplace detail page, as compact chip links. */
export function IntegrationRelatedIntegrations({
  integrations,
}: IntegrationRelatedIntegrationsProps) {
  if (integrations.length === 0) return null;

  return (
    <section className="space-y-4 rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-md">
      <h2 className="text-2xl font-medium text-foreground">
        Related integrations
      </h2>
      <div className="flex flex-wrap gap-2">
        {integrations.map((integration) => (
          <IntegrationChipLink
            key={integration.integrationId}
            integration={integration}
          />
        ))}
      </div>
    </section>
  );
}
