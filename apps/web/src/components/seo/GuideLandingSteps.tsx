import type { GuideLandingConfig } from "./guideLandingConfig";

type GuideSteps = NonNullable<GuideLandingConfig["steps"]>;
type GuideLimits = NonNullable<GuideLandingConfig["limits"]>;

export function GuideStepList({ steps }: { readonly steps: GuideSteps }) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {steps.heading}
      </h2>
      <ol className="space-y-4">
        {steps.items.map((step, index) => (
          <li key={step.name} className="rounded-2xl bg-zinc-800 p-5">
            <h3 className="mb-2 text-lg font-medium text-white">
              {index + 1}. {step.name}
            </h3>
            <p className="leading-relaxed text-zinc-400">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function GuideLimitList({ limits }: { readonly limits: GuideLimits }) {
  return (
    <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
      <h2 className="mb-4 text-2xl font-semibold text-white">
        {limits.heading}
      </h2>
      <ul className="list-disc space-y-2 pl-6 text-lg leading-relaxed text-zinc-300">
        {limits.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
