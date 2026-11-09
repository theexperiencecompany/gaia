import type { ComboSectionProps } from "./ComboSections";

export function ComboHowItWorks({ data, t }: ComboSectionProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-2 text-3xl font-semibold text-white">
        {t("automate.how_to_set_it_up")}
      </h2>
      <p className="mb-8 text-zinc-400">
        {t("automate.connect_in_steps", {
          toolA: data.toolA,
          toolB: data.toolB,
        })}
      </p>
      <ol className="space-y-6">
        {data.howItWorks.map((step, index) => (
          <li key={step.step} className="flex gap-5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/20 font-semibold text-primary">
              {index + 1}
            </div>
            <div>
              <h3 className="mb-1 text-lg font-semibold text-white">
                {step.step}
              </h3>
              <p className="leading-relaxed text-zinc-400">
                {step.description}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
