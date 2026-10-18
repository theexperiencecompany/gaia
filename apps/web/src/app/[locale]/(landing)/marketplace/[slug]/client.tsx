"use client";

import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import DocsGuidesSection from "@/components/seo/DocsGuidesSection";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationRelatedIntegrations } from "@/features/integrations/components/IntegrationRelatedIntegrations";
import { IntegrationRelatedWorkflows } from "@/features/integrations/components/IntegrationRelatedWorkflows";
import type {
  CommunityIntegration,
  PublicIntegrationResponse,
} from "@/features/integrations/types";
import type { DocsGuideLink } from "@/lib/docs-links";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import {
  type AutomateCombo,
  IntegrationAutomateGuides,
} from "./IntegrationAutomateGuides";
import { IntegrationHeader } from "./IntegrationHeader";
import { IntegrationMetaBar } from "./IntegrationMetaBar";
import { IntegrationRichContent } from "./IntegrationRichContent";
import { IntegrationToolsCard } from "./IntegrationToolsCard";
import { IntegrationUseCases } from "./IntegrationUseCases";
import { useAddIntegration } from "./useAddIntegration";

interface IntegrationDetailClientProps {
  integration: PublicIntegrationResponse;
  comparisonSlug?: string;
  alternativeSlug?: string;
  /** Server-fetched so related links render in SSR HTML for crawlers. */
  initialRelatedIntegrations?: CommunityIntegration[];
  /** Server-fetched so related links render in SSR HTML for crawlers. */
  initialRelatedWorkflows?: CommunityWorkflow[];
  /** Matching automate combos from local JSON (no backend needed). */
  automateCombos?: AutomateCombo[];
  /** Curated docs guides for this slug (server-resolved, fallback included). */
  docsGuides?: readonly DocsGuideLink[];
}

export function IntegrationDetailClient({
  integration,
  comparisonSlug,
  alternativeSlug,
  initialRelatedIntegrations,
  initialRelatedWorkflows,
  automateCombos,
  docsGuides,
}: IntegrationDetailClientProps) {
  const add = useAddIntegration(integration);

  // Prepare breadcrumbs matching use-case page format
  const breadcrumbs = [
    { label: "Home", href: "/" },
    { label: "Marketplace", href: "/marketplace" },
    {
      label:
        integration.category.charAt(0).toUpperCase() +
        integration.category.slice(1),
    },
  ];

  return (
    <div className="relative">
      <div className="flex min-h-screen w-screen justify-center overflow-y-auto pt-34 pb-20 relative z-1">
        <div className="container mx-auto w-full max-w-5xl space-y-5">
          <div className="mb-3 text-sm text-zinc-500">
            <Breadcrumbs>
              {breadcrumbs.map((crumb) => (
                <BreadcrumbItem key={crumb.label} href={crumb.href}>
                  {crumb.label}
                </BreadcrumbItem>
              ))}
            </Breadcrumbs>
          </div>

          <IntegrationHeader
            integration={integration}
            isAdding={add.isAdding}
            isAdded={add.isAdded}
            alreadyHasIntegration={add.alreadyHasIntegration}
            onAdd={add.handleAdd}
            onView={add.viewIntegration}
          />

          <IntegrationMetaBar
            integration={integration}
            isNative={add.isNative}
          />

          <IntegrationUseCases integration={integration} />

          <IntegrationToolsCard integration={integration} />

          <IntegrationRelatedWorkflows
            integrationId={integration.integrationId}
            integrationName={integration.name}
            variant="section"
            initialWorkflows={initialRelatedWorkflows}
          />

          <IntegrationRichContent
            integration={integration}
            comparisonSlug={comparisonSlug}
            alternativeSlug={alternativeSlug}
          />

          <IntegrationRelatedIntegrations
            currentSlug={integration.slug}
            category={integration.category}
            integrationName={integration.name}
            initialIntegrations={initialRelatedIntegrations}
          />

          {automateCombos && automateCombos.length > 0 && (
            <IntegrationAutomateGuides
              integrationName={integration.name}
              combos={automateCombos}
            />
          )}

          {docsGuides && docsGuides.length > 0 && (
            <DocsGuidesSection
              heading="Guides in the docs"
              guides={docsGuides}
              headingClassName="mb-2 text-2xl font-medium text-foreground"
            />
          )}
        </div>
      </div>

      <BearerTokenModal
        isOpen={add.bearer.isOpen}
        onClose={add.bearer.close}
        integrationId={add.bearer.integrationId}
        integrationName={add.bearer.integrationName}
        onSubmit={add.bearer.submit}
      />
    </div>
  );
}
