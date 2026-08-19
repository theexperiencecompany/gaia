interface AlternativeHeroProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
  readonly tagline: string;
  readonly whyPeopleLook: string;
}

export function AlternativeHero({
  t,
  name,
  tagline,
  whyPeopleLook,
}: AlternativeHeroProps) {
  return (
    <>
      <header className="mb-16">
        <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
          {t("alternatives.best_alternative_year", { name })}
        </h1>
        <p className="text-xl leading-relaxed text-zinc-400">{tagline}</p>
      </header>

      <section className="mb-16">
        <p className="text-lg leading-relaxed text-zinc-300">{whyPeopleLook}</p>
      </section>
    </>
  );
}
