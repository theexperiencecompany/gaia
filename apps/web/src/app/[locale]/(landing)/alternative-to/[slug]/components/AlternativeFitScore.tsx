import { FitScoreRow } from "./FitScore";

interface AlternativeFitScoreProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
  readonly score: number;
}

export function AlternativeFitScore({
  t,
  name,
  score,
}: AlternativeFitScoreProps) {
  return (
    <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
      <h2 className="mb-2 text-2xl font-semibold text-white">
        {t("alternatives.how_well_replace", { name })}
      </h2>
      <p className="mb-4 text-sm text-zinc-500">
        {t("alternatives.honest_fit_score")}
      </p>
      <FitScoreRow score={score} />
    </section>
  );
}
