import Link from "next/link";
import type { AlternativeData } from "@/features/alternatives/data/alternativesData";
import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";

interface AlternativeRelatedProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly relatedAlternatives: AlternativeData[];
  readonly relatedComparisons: ComparisonData[];
  readonly slug: string;
  readonly dataName: string;
  readonly hasComparisonPage: boolean;
}

export function AlternativeRelated({
  t,
  relatedAlternatives,
  relatedComparisons,
  slug,
  dataName,
  hasComparisonPage,
}: AlternativeRelatedProps) {
  return (
    <>
      {relatedAlternatives.length > 0 && (
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.more_alternatives")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {relatedAlternatives.map((alt) => (
              <Link
                key={alt.slug}
                href={`/alternative-to/${alt.slug}`}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                  {t("alternatives.best_alternative", { name: alt.name })}
                </h3>
                <p className="text-xs text-zinc-400">{alt.tagline}</p>
              </Link>
            ))}
          </div>
        </section>
      )}

      {relatedComparisons.length >= 1 && (
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.people_also_consider")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {relatedComparisons.map((comp) => (
              <Link
                key={comp.slug}
                href={`/compare/${comp.slug}`}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                  {t("alternatives.gaia_vs_name", { name: comp.name })}
                </h3>
                <p className="text-xs text-zinc-400">{comp.tagline}</p>
              </Link>
            ))}
          </div>
        </section>
      )}

      {hasComparisonPage && (
        <section className="mb-16 border-t border-zinc-800 pt-8">
          <p className="text-sm text-zinc-500">
            {t("alternatives.want_comparison")}{" "}
            <Link
              href={`/compare/${slug}`}
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              {t("alternatives.see_comparison", { name: dataName })} &rarr;
            </Link>
          </p>
        </section>
      )}
    </>
  );
}
