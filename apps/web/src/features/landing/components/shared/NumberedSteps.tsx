import type { ReactNode } from "react";

interface NumberedStep {
  name: string;
  body: ReactNode;
}

export default function NumberedSteps({
  steps,
}: {
  readonly steps: readonly NumberedStep[];
}) {
  return (
    <ol className="space-y-4 text-left">
      {steps.map((step, index) => (
        <li
          key={step.name}
          className="flex items-start gap-4 rounded-2xl bg-zinc-800/60 p-5"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-sm font-semibold text-emerald-400">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="mb-1 text-base font-semibold text-white">
              {step.name}
            </h3>
            <div className="text-sm leading-relaxed text-zinc-400">
              {step.body}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
