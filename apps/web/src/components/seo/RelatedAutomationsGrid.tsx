import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";

interface RelatedAutomationsGridProps {
  readonly heading: string;
  readonly combos: readonly IntegrationCombo[];
  readonly headingClassName?: string;
}

/** Cards linking /automate combo pages, in the visitor's locale. */
export function RelatedAutomationsGrid({
  heading,
  combos,
  headingClassName = "mb-6 text-3xl font-semibold text-white",
}: RelatedAutomationsGridProps) {
  if (combos.length === 0) return null;

  return (
    <section className="mb-16">
      <h2 className={headingClassName}>{heading}</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {combos.map((combo) => (
          <SiteLink
            key={combo.slug}
            href={`/automate/${combo.slug}`}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
              {combo.toolA} + {combo.toolB}
            </h3>
            <p className="text-xs text-zinc-400">{combo.tagline}</p>
          </SiteLink>
        ))}
      </div>
    </section>
  );
}
