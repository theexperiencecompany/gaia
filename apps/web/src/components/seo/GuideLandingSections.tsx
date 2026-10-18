import { SiteLink } from "@/components/seo/SiteLink";
import { fillCurrentYear } from "@/lib/feature-data";
import type { GuideLandingConfig, GuideSection } from "./guideLandingConfig";

export function GuideHeader({
  config,
}: {
  readonly config: GuideLandingConfig;
}) {
  return (
    <>
      <nav className="mb-8 text-sm text-zinc-500">
        <SiteLink href="/" className="hover:text-zinc-300">
          Home
        </SiteLink>
        <span className="mx-2">/</span>
        <span className="text-zinc-300">{config.breadcrumbName}</span>
      </nav>
      <header className="mb-16">
        <h1 className="mb-6 font-serif text-5xl font-normal text-white md:text-6xl">
          {fillCurrentYear(config.heading)}
        </h1>
        <div className="rounded-3xl bg-zinc-800 p-8">
          <p className="text-xl leading-relaxed text-zinc-200">
            {config.answer}
          </p>
        </div>
      </header>
    </>
  );
}

export function GuideBodySection({
  section,
}: {
  readonly section: GuideSection;
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">
        {section.heading}
      </h2>
      <div className="space-y-4 text-lg leading-relaxed text-zinc-300">
        {section.paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
      {section.bullets && (
        <ul className="mt-6 list-disc space-y-2 pl-6 text-lg leading-relaxed text-zinc-300">
          {section.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
