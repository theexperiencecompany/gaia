import type { getTranslations } from "next-intl/server";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";

export type Translator = Awaited<ReturnType<typeof getTranslations>>;

export interface ComboSectionProps {
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
