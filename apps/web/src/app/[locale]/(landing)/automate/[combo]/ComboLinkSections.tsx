import { Button } from "@heroui/button";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import type { Translator } from "./ComboSections";

interface ComboLinksProps {
  readonly data: IntegrationCombo;
  readonly t: Translator;
}

export function ComboIntegrationLinks({
  data,
  toolAHref,
  toolBHref,
  t,
}: ComboLinksProps & {
  readonly toolAHref: string;
  readonly toolBHref: string;
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        {t("automate.explore_integrations")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <SiteLink
          href={toolAHref}
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("automate.tool_integration", { tool: data.toolA })}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("automate.see_everything_gaia", { tool: data.toolA })}
          </p>
        </SiteLink>
        <SiteLink
          href={toolBHref}
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("automate.tool_integration", { tool: data.toolB })}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("automate.discover_automations", { tool: data.toolB })}
          </p>
        </SiteLink>
      </div>
    </section>
  );
}

function CompareCard({
  href,
  toolName,
}: {
  readonly href: string;
  readonly toolName: string;
}) {
  return (
    <SiteLink
      href={href}
      className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
        GAIA vs {toolName}: full comparison
      </h3>
      <p className="text-sm leading-relaxed text-zinc-400">
        See how GAIA compares to {toolName} head-to-head.
      </p>
    </SiteLink>
  );
}

export function ComboCompareLinks({
  data,
  toolACompareHref,
  toolBCompareHref,
}: Pick<ComboLinksProps, "data"> & {
  readonly toolACompareHref: string | null;
  readonly toolBCompareHref: string | null;
}) {
  if (!toolACompareHref && !toolBCompareHref) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        Compare the tools
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {toolACompareHref && (
          <CompareCard href={toolACompareHref} toolName={data.toolA} />
        )}
        {toolBCompareHref && (
          <CompareCard href={toolBCompareHref} toolName={data.toolB} />
        )}
      </div>
    </section>
  );
}

export function ComboRelated({
  relatedCombos,
  t,
}: Pick<ComboLinksProps, "t"> & {
  readonly relatedCombos: readonly IntegrationCombo[];
}) {
  if (relatedCombos.length === 0) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        {t("common.related_automations")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {relatedCombos.map((related) => (
          <SiteLink
            key={related.slug}
            href={`/automate/${related.slug}`}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
              {related.toolA} + {related.toolB}
            </h3>
            <p className="text-xs text-zinc-400">{related.tagline}</p>
          </SiteLink>
        ))}
      </div>
    </section>
  );
}

export function ComboMoreLink({ t }: Pick<ComboLinksProps, "t">) {
  return (
    <section className="mb-16">
      <div className="rounded-3xl bg-zinc-800 p-8">
        <h2 className="mb-3 text-2xl font-semibold text-white">
          {t("automate.explore_more_combos")}
        </h2>
        <p className="mb-6 leading-relaxed text-zinc-400">
          {t("automate.gaia_supports_combos")}
        </p>
        <Button as="a" href="/marketplace" color="primary" radius="full">
          {t("common.browse_marketplace")}
        </Button>
      </div>
    </section>
  );
}
