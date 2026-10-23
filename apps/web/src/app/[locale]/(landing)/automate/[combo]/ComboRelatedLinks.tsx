import { Button } from "@heroui/button";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import type { ComboSectionProps } from "./ComboSections";

export function ComboRelated({
  relatedCombos,
  t,
}: Pick<ComboSectionProps, "t"> & {
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

export function ComboMoreLink({ t }: Pick<ComboSectionProps, "t">) {
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
