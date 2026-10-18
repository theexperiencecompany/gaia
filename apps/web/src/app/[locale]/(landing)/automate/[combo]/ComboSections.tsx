import type { getTranslations } from "next-intl/server";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";

export type Translator = Awaited<ReturnType<typeof getTranslations>>;

interface ComboSectionProps {
  readonly data: IntegrationCombo;
  readonly t: Translator;
}

export function ComboBreadcrumb({ data, t }: ComboSectionProps) {
  return (
    <nav className="mb-8 text-sm text-zinc-500">
      <SiteLink href="/" className="hover:text-zinc-300">
        {t("common.home")}
      </SiteLink>
      <span className="mx-2">/</span>
      <SiteLink href="/marketplace" className="hover:text-zinc-300">
        {t("marketplace.breadcrumb")}
      </SiteLink>
      <span className="mx-2">/</span>
      <span className="text-zinc-300">
        {data.toolA} + {data.toolB}
      </span>
    </nav>
  );
}

export function ComboHero({ data, t }: ComboSectionProps) {
  return (
    <header className="mb-16">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span className="inline-flex items-center rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-400">
          {t("common.integration")}
        </span>
        <span className="inline-flex items-center rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          {t("common.powered_by_gaia")}
        </span>
      </div>
      <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
        {t("automate.automate_with_gaia", {
          toolA: data.toolA,
          toolB: data.toolB,
        })}
      </h1>
      <p className="text-xl leading-relaxed text-zinc-400">{data.tagline}</p>
    </header>
  );
}

export function ComboIntro({ data }: Pick<ComboSectionProps, "data">) {
  return (
    <section className="mb-16">
      {data.intro.split("\n\n").map((paragraph) => (
        <p
          key={paragraph.slice(0, 40)}
          className="mb-4 text-lg leading-relaxed text-zinc-300 last:mb-0"
        >
          {paragraph}
        </p>
      ))}
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
