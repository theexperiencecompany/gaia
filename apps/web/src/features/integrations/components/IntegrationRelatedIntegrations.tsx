"use client";

import { useQuery } from "@tanstack/react-query";

import { integrationsApi } from "../api/integrationsApi";
import { PublicIntegrationCard } from "./PublicIntegrationCard";

interface IntegrationRelatedIntegrationsProps {
  /** Slug of the integration currently being viewed (excluded from results). */
  readonly currentSlug: string;
  /** Category used to find similar integrations. */
  readonly category: string;
  /** Name of the current integration, for the section copy. */
  readonly integrationName?: string;
  /** Max number of related integrations to show. */
  readonly limit?: number;
}

function getCategoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1).toLowerCase();
}

/**
 * "Related integrations" section for a marketplace detail page — same-category
 * integrations rendered as PublicIntegrationCard (real <Link> anchors). Mirrors
 * IntegrationRelatedWorkflows; gives every detail page contextual internal
 * links to its siblings so they aren't orphaned.
 */
export function IntegrationRelatedIntegrations({
  currentSlug,
  category,
  integrationName,
  limit = 6,
}: IntegrationRelatedIntegrationsProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["related-integrations", category, currentSlug, limit],
    queryFn: () =>
      integrationsApi.getCommunityIntegrations({
        category,
        sort: "popular",
        limit: limit + 1,
      }),
    staleTime: 5 * 60 * 1000,
    enabled: !!category,
  });

  if (isLoading) return null;

  const integrations = (data?.integrations ?? [])
    .filter((integration) => integration.slug !== currentSlug)
    .slice(0, limit);

  if (integrations.length === 0) return null;

  return (
    <section className="space-y-6 rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-md">
      <div>
        <h2 className="mb-2 text-2xl font-medium text-foreground">
          Related integrations
        </h2>
        <p className="text-sm leading-relaxed text-zinc-400">
          {integrationName
            ? `More ${getCategoryLabel(category)} integrations like ${integrationName} you can connect to GAIA.`
            : "More integrations in this category you can connect to GAIA."}
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
