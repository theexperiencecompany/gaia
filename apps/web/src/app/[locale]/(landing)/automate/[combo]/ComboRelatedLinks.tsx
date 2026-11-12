import { LinkButton } from "@/components/shared/LinkButton";
import type { ComboSectionProps } from "./ComboSections";

export function ComboMoreLink({ t }: Pick<ComboSectionProps, "t">) {
  return (
    <section className="mb-16">
      <div className="rounded-3xl bg-zinc-800 p-8">
        <h2 className="mb-3 text-2xl font-semibold text-white">
          {t("automate.explore_more_combos")}
        </h2>
        <p className="mb-6 leading-relaxed text-zinc-400">
          {t("automate.gaia_supports_combos")}
        </p>
        <LinkButton
          href="/marketplace"
          variant="primary"
          className="rounded-full"
        >
          {t("common.browse_marketplace")}
        </LinkButton>
      </div>
    </section>
  );
}
