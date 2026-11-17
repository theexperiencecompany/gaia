import { SiteLink } from "@/components/seo/SiteLink";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { marketplacePath } from "@/features/integrations/lib/marketplaceSlug";
import type { CommunityIntegration } from "../types";

interface IntegrationRelatedIntegrationsProps {
  /** Server-picked by relatedIntegrations, so the links are in the SSR HTML. */
  readonly integrations: readonly CommunityIntegration[];
}

/** "Related integrations" on a marketplace detail page: a light row per integration, icon, name and one line of what it does. */
export function IntegrationRelatedIntegrations({
  integrations,
}: IntegrationRelatedIntegrationsProps) {
  if (integrations.length === 0) return null;

  return (
    <section className="space-y-4 rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-md">
      <h2 className="text-2xl font-medium text-foreground">
        Related integrations
      </h2>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {integrations.map((integration) => (
          <li key={integration.integrationId}>
            <SiteLink
              href={marketplacePath(integration.slug)}
              className="flex h-full items-start gap-3 rounded-2xl bg-zinc-800 p-3 transition-colors hover:bg-zinc-700/60"
            >
              {getToolCategoryIcon(
                integration.integrationId,
                { size: 20, width: 20, height: 20, showBackground: false },
                integration.iconUrl,
              )}
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-100">
                  {integration.name}
                </span>
                <span className="line-clamp-2 text-xs text-zinc-400">
                  {integration.description}
                </span>
              </span>
            </SiteLink>
          </li>
        ))}
      </ul>
    </section>
  );
}
