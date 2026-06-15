const COSTS: { label: string; credits: string }[] = [
  { label: "Chat message", credits: "7–80" },
  { label: "Web search", credits: "100" },
  { label: "Image generation", credits: "500" },
  { label: "Deep research", credits: "500–1,500" },
];

const TIERS: { label: string; credits: string }[] = [
  { label: "Free", credits: "7,500 / mo" },
  { label: "Pro", credits: "200,000 / mo" },
  { label: "Max", credits: "1,000,000 / mo" },
];

/** Pricing-page transparency: explains the credit unit and what things cost. */
export function CreditExplainer() {
  return (
    <div className="mb-20 flex w-full max-w-2xl flex-col items-center gap-5 px-4 text-center">
      <p className="text-lg text-zinc-200">
        Every plan runs on <span className="text-white">credits</span> — our
        unit of AI compute.{" "}
        <span className="text-zinc-500">10,000 credits = $1 of usage.</span>
      </p>

      <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-2xl bg-zinc-900/50 p-5 text-left backdrop-blur-sm">
          <p className="mb-3 text-xs font-medium tracking-wide text-zinc-500 uppercase">
            Monthly credits
          </p>
          <div className="space-y-2">
            {TIERS.map((t) => (
              <div key={t.label} className="flex justify-between text-sm">
                <span className="text-zinc-300">{t.label}</span>
                <span className="text-zinc-400">{t.credits}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl bg-zinc-900/50 p-5 text-left backdrop-blur-sm">
          <p className="mb-3 text-xs font-medium tracking-wide text-zinc-500 uppercase">
            What uses credits
          </p>
          <div className="space-y-2">
            {COSTS.map((c) => (
              <div key={c.label} className="flex justify-between text-sm">
                <span className="text-zinc-300">{c.label}</span>
                <span className="text-zinc-400">{c.credits} credits</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p className="text-xs text-zinc-500">
        Pro and Max can top up anytime. Credits don't roll over month to month.
      </p>
    </div>
  );
}
