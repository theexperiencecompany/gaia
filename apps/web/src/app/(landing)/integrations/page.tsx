import type { Metadata } from "next";
import Link from "next/link";

import JsonLd from "@/components/seo/JsonLd";
import {
  getAllCombos,
  type IntegrationCombo,
} from "@/features/integrations/data/combosData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Tool Integrations - Automate Any Two Apps Together",
  description:
    "Explore GAIA's cross-app automation combos. Connect Gmail with Slack, Notion with Linear, GitHub with Asana, and 25+ other tool pairs. No code required.",
  path: "/integrations",
  keywords: [
    "tool integrations",
    "app automation combos",
    "workflow automation",
    "connect two apps",
    "cross-tool automation",
    "Gmail Slack integration",
    "Notion Linear integration",
    "GitHub automation",
    "GAIA integrations",
  ],
});

const PRIMARY_TOOL_ORDER = [
  "Gmail",
  "Slack",
  "GitHub",
  "Notion",
  "Linear",
  "Google Calendar",
  "Todoist",
  "Asana",
  "Zoom",
  "HubSpot",
];

function groupCombosByPrimaryTool(
  combos: IntegrationCombo[],
): Map<string, IntegrationCombo[]> {
  const grouped = new Map<string, IntegrationCombo[]>();

  for (const toolName of PRIMARY_TOOL_ORDER) {
    grouped.set(toolName, []);
  }

  for (const combo of combos) {
    const existing = grouped.get(combo.toolA);
    if (existing) {
      existing.push(combo);
    } else {
      grouped.set(combo.toolA, [combo]);
    }
  }

  // Remove empty groups
  for (const [key, val] of grouped.entries()) {
    if (val.length === 0) {
      grouped.delete(key);
    }
  }

  return grouped;
}

export default function IntegrationsHubPage() {
  const combos = getAllCombos();
  const grouped = groupCombosByPrimaryTool(combos);

  const webPageSchema = generateWebPageSchema(
    "Tool Integration Combos - Automate Any Two Apps with GAIA",
    "Explore cross-app automation combos powered by GAIA. Connect Gmail, Slack, Notion, GitHub, Linear, and 10+ other tools in any combination.",
    `${siteConfig.url}/integrations`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Integrations", url: `${siteConfig.url}/integrations` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Integrations", url: `${siteConfig.url}/integrations` },
  ]);

  const itemListSchema = generateItemListSchema(
    combos.map((c) => ({
      name: `${c.toolA} + ${c.toolB} Automation`,
      url: `${siteConfig.url}/integrations/${c.slug}`,
      description: c.tagline,
    })),
    "Article",
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <div className="mb-4 inline-flex items-center rounded-full bg-primary/10 px-4 py-1.5 text-sm font-medium text-primary">
            {combos.length} automation combos
          </div>
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            Automate any two tools together
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            GAIA connects your favorite apps so they work as one unified
            workflow. Pick any two tools and see exactly what gets automated.
          </p>
        </header>

        {/* Stats row */}
        <div className="mb-16 grid grid-cols-3 gap-4 rounded-3xl bg-zinc-800 p-6">
          <div className="text-center">
            <p className="text-3xl font-semibold text-white">{combos.length}</p>
            <p className="text-sm text-zinc-500">Combo automations</p>
          </div>
          <div className="text-center">
            <p className="text-3xl font-semibold text-white">
              {PRIMARY_TOOL_ORDER.length}+
            </p>
            <p className="text-sm text-zinc-500">Tools supported</p>
          </div>
          <div className="text-center">
            <p className="text-3xl font-semibold text-white">0</p>
            <p className="text-sm text-zinc-500">Lines of code needed</p>
          </div>
        </div>

        {/* Grouped by primary tool */}
        <div className="space-y-16">
          {Array.from(grouped.entries()).map(([toolName, toolCombos]) => (
            <section key={toolName}>
              <div className="mb-6 flex items-center gap-4">
                <h2 className="text-2xl font-semibold text-white">
                  {toolName} automations
                </h2>
                <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-500">
                  {toolCombos.length} combos
                </span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {toolCombos.map((combo) => (
                  <Link
                    key={combo.slug}
                    href={`/integrations/${combo.slug}`}
                    className="group flex flex-col gap-3 rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded-lg bg-zinc-700 px-2.5 py-1 text-xs font-medium text-zinc-300">
                        {combo.toolA}
                      </span>
                      <span className="text-zinc-600">+</span>
                      <span className="rounded-lg bg-zinc-700 px-2.5 py-1 text-xs font-medium text-zinc-300">
                        {combo.toolB}
                      </span>
                    </div>
                    <h3 className="text-base font-medium text-white transition-colors group-hover:text-primary">
                      {combo.toolA} + {combo.toolB} Automation
                    </h3>
                    <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                      {combo.tagline}
                    </p>
                    <span className="mt-auto text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                      See {combo.useCases.length} automations &rarr;
                    </span>
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>

        {/* Bottom CTA */}
        <div className="mt-20 rounded-3xl bg-zinc-800 p-8 text-center">
          <h2 className="mb-3 text-2xl font-semibold text-white">
            Don&apos;t see your combo?
          </h2>
          <p className="mb-6 text-zinc-400">
            GAIA supports 50+ integrations. Connect any tool from the
            marketplace and build custom multi-tool workflows.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Link
              href="/marketplace"
              className="inline-flex items-center gap-2 rounded-full border border-zinc-700 px-6 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-white"
            >
              Browse marketplace
            </Link>
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              Try GAIA free
            </Link>
          </div>
        </div>
      </div>

      <FinalSection />
    </>
  );
}
