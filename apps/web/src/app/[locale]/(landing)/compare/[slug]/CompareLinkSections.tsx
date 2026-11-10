import type { getTranslations } from "next-intl/server";
import { SiteLink } from "@/components/seo/SiteLink";
import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";
import type { PersonaData } from "@/features/personas/data/personasData";

type Translator = Awaited<ReturnType<typeof getTranslations>>;

interface CompareLinkSectionsProps {
  readonly name: string;
  readonly alternativeHref: string | null;
  readonly category: string;
  readonly relatedComparisons: readonly ComparisonData[];
  readonly relatedPersonas: readonly PersonaData[];
  readonly t: Translator;
}

export function CompareRelatedSections({
  name,
  alternativeHref,
  category,
  relatedComparisons,
  relatedPersonas,
  t,
}: CompareLinkSectionsProps) {
  return (
    <>
      {alternativeHref && (
        <section className="mb-16 border-t border-zinc-800 pt-8">
          <p className="text-sm text-zinc-500">
            {t("comparisons.looking_for_alternative", { name })}{" "}
            <SiteLink
              href={alternativeHref}
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              {t("comparisons.see_complete_guide")} &rarr;{" "}
              {t("comparisons.best_alternative_year", { name })}
            </SiteLink>
          </p>
        </section>
      )}

      {relatedComparisons.length > 0 && (
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("comparisons.compare_more_tools", { category })}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {relatedComparisons.map((comp) => (
              <SiteLink
                key={comp.slug}
                href={`/compare/${comp.slug}`}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                  {t("comparisons.gaia_vs", { name: comp.name })}
                </h3>
                <p className="text-xs text-zinc-400">{comp.tagline}</p>
              </SiteLink>
            ))}
          </div>
        </section>
      )}

      {relatedPersonas.length > 0 && (
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("comparisons.gaia_for_role")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {relatedPersonas.map((persona) => (
              <SiteLink
                key={persona.slug}
                href={`/for/${persona.slug}`}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-2 text-base font-medium text-white group-hover:text-primary">
                  {t("comparisons.gaia_for_persona", { role: persona.role })}
                </h3>
                <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
                  {persona.metaDescription}
                </p>
              </SiteLink>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

export function CompareExploreMore({
  name,
  t,
}: Pick<CompareLinkSectionsProps, "name" | "t">) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("common.explore_more")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <SiteLink
          href="/learn"
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("comparisons.ai_glossary")}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("comparisons.ai_glossary_desc", { name })}
          </p>
        </SiteLink>
        <SiteLink
          href="/for"
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("comparisons.gaia_for_role")}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("comparisons.gaia_for_role_desc")}
          </p>
        </SiteLink>
      </div>
    </section>
  );
}
