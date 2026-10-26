import type { ComponentProps } from "react";
import { ComboAppIcons } from "@/components/seo/ComboAppIcons";
import { HubGroupSection } from "@/components/seo/HubGroupSection";
import { SiteLink } from "@/components/seo/SiteLink";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import { comboAppsOf } from "@/features/integrations/lib/comboApps";

type RelatedAutomationsGridProps = Omit<
  ComponentProps<typeof HubGroupSection>,
  "children"
> & {
  readonly combos: readonly IntegrationCombo[];
};

function ComboCard({ combo }: { readonly combo: IntegrationCombo }) {
  return (
    <SiteLink
      href={`/automate/${combo.slug}`}
      className="group flex flex-col gap-2 rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <span className="flex items-center gap-3">
        <ComboAppIcons apps={comboAppsOf(combo)} />
        <h3 className="text-base font-medium text-white group-hover:text-primary">
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
  ...section
}: RelatedAutomationsGridProps) {
  if (combos.length === 0) return null;

  return (
    <HubGroupSection {...section}>
      <div className="grid gap-4 sm:grid-cols-3">
        {combos.map((combo) => (
          <ComboCard key={combo.slug} combo={combo} />
        ))}
      </div>
    </HubGroupSection>
  );
}
