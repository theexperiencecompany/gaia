interface AlternativeMigrationProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
  readonly steps: string[];
}

export function AlternativeMigration({
  t,
  name,
  steps,
}: AlternativeMigrationProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("alternatives.how_to_migrate", { name })}
      </h2>
      <ol className="space-y-4">
        {steps.map((step, index) => (
          <li
            key={step}
            className="flex items-start gap-4 rounded-2xl bg-zinc-800 p-5"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-sm font-semibold text-emerald-400">
              {index + 1}
            </span>
            <span className="mt-1 text-zinc-300">{step}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
