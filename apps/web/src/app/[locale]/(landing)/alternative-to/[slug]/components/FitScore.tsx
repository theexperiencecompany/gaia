function FitScorePip({ filled }: { readonly filled: boolean }) {
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${filled ? "bg-emerald-400" : "bg-zinc-700"}`}
    />
  );
}

export function FitScoreRow({ score }: { readonly score: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {[0, 1, 2, 3, 4].map((i) => (
        <FitScorePip key={`pip-${i}`} filled={i < score} />
      ))}
      <span className="ml-1 text-sm text-zinc-400">{score}/5</span>
    </div>
  );
}
