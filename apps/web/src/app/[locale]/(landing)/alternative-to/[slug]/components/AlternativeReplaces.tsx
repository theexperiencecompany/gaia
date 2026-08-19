interface AlternativeReplacesProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
  readonly replaces: string[];
}

export function AlternativeReplaces({
  t,
  name,
  replaces,
}: AlternativeReplacesProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("alternatives.what_gaia_replaces", { name })}
      </h2>
      <ul className="space-y-3">
        {replaces.map((item) => (
          <li key={item} className="flex items-start gap-3 text-zinc-300">
            <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
