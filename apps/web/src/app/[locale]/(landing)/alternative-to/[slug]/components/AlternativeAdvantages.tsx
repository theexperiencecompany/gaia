interface AlternativeAdvantagesProps {
  readonly t: (key: string) => string;
  readonly advantages: string[];
}

export function AlternativeAdvantages({
  t,
  advantages,
}: AlternativeAdvantagesProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("alternatives.where_gaia_further")}
      </h2>
      <ul className="space-y-3">
        {advantages.map((advantage) => (
          <li key={advantage} className="flex items-start gap-3 text-zinc-300">
            <span className="mt-1 shrink-0 text-emerald-400">+</span>
            <span>{advantage}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
