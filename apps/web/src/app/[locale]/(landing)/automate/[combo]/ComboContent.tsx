import { ProseParagraphs } from "@/components/seo/ProseParagraphs";
import type { ComboSectionProps } from "./ComboSections";

export function ComboIntro({ data }: Pick<ComboSectionProps, "data">) {
  return (
    <section className="mb-16">
      <ProseParagraphs
        text={data.intro}
        className="text-lg leading-relaxed text-zinc-300"
      />
    </section>
  );
}

export function ComboUseCases({ data, t }: ComboSectionProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-2 text-3xl font-semibold text-white">
        {data.useCases.length} {t("automate.things_you_can_automate")}
      </h2>
      <p className="mb-8 text-zinc-400">
        {t("automate.everything_gaia_can_do", {
          toolA: data.toolA,
          toolB: data.toolB,
        })}
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.useCases.map((useCase, index) => (
          <div
            key={useCase.title}
            className="rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <div className="mb-3 flex items-start gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20 text-sm font-semibold text-primary">
                {index + 1}
              </span>
              <h3 className="text-base font-semibold text-white">
                {useCase.title}
              </h3>
            </div>
            <p className="text-sm leading-relaxed text-zinc-400">
              {useCase.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
