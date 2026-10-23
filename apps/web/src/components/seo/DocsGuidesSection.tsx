import type { DocsGuideLink } from "@/lib/docs-links";

interface DocsGuidesSectionProps {
  readonly heading: string;
  readonly guides: readonly DocsGuideLink[];
  readonly headingClassName?: string;
}

/**
 * "Guides in the Docs" related-links section shared by the programmatic
 * marketing templates. Renders nothing when the slug has no mapped guides.
 */
export default function DocsGuidesSection({
  heading,
  guides,
  headingClassName = "mb-6 text-3xl font-semibold text-white",
}: DocsGuidesSectionProps) {
  if (guides.length === 0) {
    return null;
  }
  return (
    <section className="mb-16">
      <h2 className={headingClassName}>{heading}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {guides.map((guide) => (
          <a
            key={guide.url}
            href={guide.url}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
              {guide.title}
            </h3>
            <p className="text-sm leading-relaxed text-zinc-400">
              docs.heygaia.io
            </p>
          </a>
        ))}
      </div>
    </section>
  );
}
