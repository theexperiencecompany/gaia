interface AlternativePainPointsProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
  readonly painPoints: string[];
}

export function AlternativePainPoints({
  t,
  name,
  painPoints,
}: AlternativePainPointsProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("alternatives.why_people_look", { name })}
      </h2>
      <ul className="space-y-4">
        {painPoints.map((point) => (
          <li
            key={point}
            className="flex items-start gap-3 rounded-2xl bg-zinc-800 p-4 text-zinc-300"
          >
            <span className="mt-0.5 shrink-0 text-red-400">&#x2212;</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
