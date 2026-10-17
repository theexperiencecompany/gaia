import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { IntegrationCombo } from "@/features/integrations/data/combosData";

interface ToolLink {
  readonly tool: string;
  readonly href: string;
  readonly compareHref: string | null;
}

/** The three link grids below the FAQ: marketplace integrations, head-to-head
 * comparisons and related automate combos. */
export default async function AutomateComboLinks({
  tools,
  relatedCombos,
}: {
  readonly tools: readonly [ToolLink, ToolLink];
  readonly relatedCombos: readonly IntegrationCombo[];
}) {
  const t = await getTranslations();
  const [toolA, toolB] = tools;

  return (
    <>
      {/* Integration Links */}
      <section className="mb-16">
        <h2 className="mb-6 text-2xl font-semibold text-white">
          {t("automate.explore_integrations")}
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Link
            href={toolA.href}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
              {t("automate.tool_integration", { tool: toolA.tool })}
            </h3>
            <p className="text-sm leading-relaxed text-zinc-400">
              {t("automate.see_everything_gaia", { tool: toolA.tool })}
            </p>
          </Link>
          <Link
            href={toolB.href}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
              {t("automate.tool_integration", { tool: toolB.tool })}
            </h3>
            <p className="text-sm leading-relaxed text-zinc-400">
              {t("automate.discover_automations", { tool: toolB.tool })}
            </p>
          </Link>
        </div>
      </section>

      {/* Compare the tools */}
      {(toolA.compareHref || toolB.compareHref) && (
        <section className="mb-16">
          <h2 className="mb-6 text-2xl font-semibold text-white">
            Compare the tools
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {toolA.compareHref && (
              <Link
                href={toolA.compareHref}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                  GAIA vs {toolA.tool}: full comparison
                </h3>
                <p className="text-sm leading-relaxed text-zinc-400">
                  See how GAIA compares to {toolA.tool} head-to-head.
                </p>
              </Link>
            )}
            {toolB.compareHref && (
              <Link
                href={toolB.compareHref}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                  GAIA vs {toolB.tool}: full comparison
                </h3>
                <p className="text-sm leading-relaxed text-zinc-400">
                  See how GAIA compares to {toolB.tool} head-to-head.
                </p>
              </Link>
            )}
          </div>
        </section>
      )}

      {/* Related Automations */}
      {relatedCombos.length > 0 && (
        <section className="mb-16">
          <h2 className="mb-6 text-2xl font-semibold text-white">
            {t("common.related_automations")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {relatedCombos.map((related) => (
              <Link
                key={related.slug}
                href={`/automate/${related.slug}`}
                className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                  {related.toolA} + {related.toolB}
                </h3>
                <p className="text-xs text-zinc-400">{related.tagline}</p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
