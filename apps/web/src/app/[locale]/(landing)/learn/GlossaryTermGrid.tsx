import { SiteLink } from "@/components/seo/SiteLink";
import type { GlossaryTerm } from "@/features/glossary/data/glossaryData";

/** Cards linking /learn term pages: the term over its definition, one level under the heading above the grid. */
export function GlossaryTermGrid({
  terms,
  headingLevel,
}: {
  readonly terms: readonly Pick<GlossaryTerm, "slug" | "term" | "definition">[];
  readonly headingLevel: "h2" | "h3";
}) {
  const Heading = headingLevel;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {terms.map((term) => (
        <SiteLink
          key={term.slug}
          href={`/learn/${term.slug}`}
          className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <Heading className="mb-2 text-lg font-semibold text-white transition-colors group-hover:text-accent">
            {term.term}
          </Heading>
          <p className="line-clamp-3 text-sm leading-relaxed text-zinc-400">
            {term.definition}
          </p>
        </SiteLink>
      ))}
    </div>
  );
}
