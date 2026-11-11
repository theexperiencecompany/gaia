import type { BestHubUseCase } from "./bestAssistantHubConfig";

export function BestHubUseCases({
  sections,
}: {
  readonly sections: readonly BestHubUseCase[];
}) {
  return sections.map((section) => (
    <section key={section.heading} className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">
        {section.heading}
      </h2>
      <div className="space-y-4 text-lg leading-relaxed text-zinc-300">
        {section.body}
      </div>
    </section>
  ));
}
