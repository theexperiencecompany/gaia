import type { CommunityIntegration } from "../types";
import { PublicIntegrationCard } from "./PublicIntegrationCard";

interface IntegrationRelatedIntegrationsProps {
  /** Server-picked by relatedIntegrations, so the links are in the SSR HTML. */
  readonly integrations: readonly CommunityIntegration[];
}

/** "Related integrations" on a marketplace detail page, as real card links. */
export function IntegrationRelatedIntegrations({
  integrations,
}: IntegrationRelatedIntegrationsProps) {
  if (integrations.length === 0) return null;

  return (
    <section className="space-y-6 rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-md">
      <div>
        <h2 className="mb-2 text-2xl font-medium text-foreground">
          Related integrations
        </h2>
        <p className="text-sm leading-relaxed text-zinc-400">
          More integrations you can connect to GAIA.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {integrations.map((integration) => (
          <PublicIntegrationCard
            key={integration.integrationId}
            integration={integration}
          />
        ))}
      </div>
    </section>
  );
}
