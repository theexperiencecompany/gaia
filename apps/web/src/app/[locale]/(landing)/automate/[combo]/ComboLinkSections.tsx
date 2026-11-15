import { SiteLink } from "@/components/seo/SiteLink";
import type { ComboSectionProps } from "./ComboSections";

/** A linked card: its title over one line of body copy. */
function LinkCard({
  href,
  title,
  body,
}: {
  readonly href: string;
  readonly title: string;
  readonly body: string;
}) {
  return (
    <SiteLink
      href={href}
      className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-accent">
        {title}
      </h3>
      <p className="text-sm leading-relaxed text-zinc-400">{body}</p>
    </SiteLink>
  );
}

export function ComboIntegrationLinks({
  data,
  toolAHref,
  toolBHref,
  t,
}: ComboSectionProps & {
  readonly toolAHref: string | null;
  readonly toolBHref: string | null;
}) {
  if (!toolAHref && !toolBHref) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        {t("automate.explore_integrations")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {toolAHref && (
          <LinkCard
            href={toolAHref}
            title={t("automate.tool_integration", { tool: data.toolA })}
            body={t("automate.see_everything_gaia", { tool: data.toolA })}
          />
        )}
        {toolBHref && (
          <LinkCard
            href={toolBHref}
            title={t("automate.tool_integration", { tool: data.toolB })}
            body={t("automate.discover_automations", { tool: data.toolB })}
          />
        )}
      </div>
    </section>
  );
}

export function ComboCompareLinks({
  data,
  toolACompareHref,
  toolBCompareHref,
  t,
}: ComboSectionProps & {
  readonly toolACompareHref: string | null;
  readonly toolBCompareHref: string | null;
}) {
  if (!toolACompareHref && !toolBCompareHref) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        {t("automate.compare_tools")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {toolACompareHref && (
          <LinkCard
            href={toolACompareHref}
            title={t("automate.compare_tool_title", { tool: data.toolA })}
            body={t("automate.compare_tool_body", { tool: data.toolA })}
          />
        )}
        {toolBCompareHref && (
          <LinkCard
            href={toolBCompareHref}
            title={t("automate.compare_tool_title", { tool: data.toolB })}
            body={t("automate.compare_tool_body", { tool: data.toolB })}
          />
        )}
      </div>
    </section>
  );
}
