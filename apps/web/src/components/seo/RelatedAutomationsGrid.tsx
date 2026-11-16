import type { ImageProps } from "next/image";
import type { ComponentProps } from "react";
import { ComboAppIcons } from "@/components/seo/ComboAppIcons";
import { HubGroupSection } from "@/components/seo/HubGroupSection";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import { comboAppsOf } from "@/features/integrations/lib/comboApps";
import { hubCardLoading } from "@/lib/hubPagination";

type RelatedAutomationsGridProps = Omit<
  ComponentProps<typeof HubGroupSection>,
  "children"
> & {
  readonly combos: readonly IntegrationCombo[];
  /** True where the grid starts in the first viewport, so its first row loads eagerly. */
  readonly opensInView?: boolean;
};

function ComboCard({
  combo,
  loading,
}: {
  readonly combo: IntegrationCombo;
  readonly loading: ImageProps["loading"];
}) {
  return (
    <SiteLink
      href={`/automate/${combo.slug}`}
      className="group flex flex-col gap-2 rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <span className="flex items-center gap-3">
        <ComboAppIcons apps={comboAppsOf(combo)} loading={loading} />
        <h3 className="text-base font-medium text-white group-hover:text-accent">
          {combo.toolA} + {combo.toolB}
        </h3>
      </span>
      <p className="line-clamp-2 text-xs text-zinc-400">{combo.tagline}</p>
    </SiteLink>
  );
}

/** Cards linking /automate combo pages, each led by its two app logos, in the visitor's locale. */
export function RelatedAutomationsGrid({
  combos,
  opensInView = false,
  ...section
}: RelatedAutomationsGridProps) {
  if (combos.length === 0) return null;

  return (
    <HubGroupSection {...section}>
      <div className="grid gap-4 sm:grid-cols-3">
        {combos.map((combo, index) => (
          <ComboCard
            key={combo.slug}
            combo={combo}
            loading={opensInView ? hubCardLoading(0, index) : "lazy"}
          />
        ))}
      </div>
    </HubGroupSection>
  );
}
