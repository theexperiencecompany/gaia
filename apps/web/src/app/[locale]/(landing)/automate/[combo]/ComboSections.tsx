import type { getTranslations } from "next-intl/server";
import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";

export type Translator = Awaited<ReturnType<typeof getTranslations>>;

export interface ComboSectionProps {
  readonly data: IntegrationCombo;
  readonly t: Translator;
}

export function ComboBreadcrumb({ data, t }: ComboSectionProps) {
  return (
    <PageBreadcrumbs
      className="mb-8"
      items={[
        { label: t("common.home"), href: "/" },
        { label: t("automate.breadcrumb"), href: "/automate" },
        { label: `${data.toolA} + ${data.toolB}` },
      ]}
    />
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
