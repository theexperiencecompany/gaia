import { SiteLink } from "@/components/seo/SiteLink";
import type { ComboSectionProps } from "./ComboSections";

function IntegrationCard({
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
          <IntegrationCard
            href={toolAHref}
            title={t("automate.tool_integration", { tool: data.toolA })}
            body={t("automate.see_everything_gaia", { tool: data.toolA })}
          />
        )}
        {toolBHref && (
          <IntegrationCard
            href={toolBHref}
            title={t("automate.tool_integration", { tool: data.toolB })}
            body={t("automate.discover_automations", { tool: data.toolB })}
          />
        )}
      </div>
    </section>
  );
}

function CompareCard({
  href,
  toolName,
}: {
  readonly href: string;
  readonly toolName: string;
}) {
  return (
    <SiteLink
      href={href}
      className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-accent">
        GAIA vs {toolName}: full comparison
      </h3>
      <p className="text-sm leading-relaxed text-zinc-400">
        See how GAIA compares to {toolName} head-to-head.
      </p>
    </SiteLink>
  );
}

export function ComboCompareLinks({
  data,
  toolACompareHref,
  toolBCompareHref,
}: Pick<ComboSectionProps, "data"> & {
  readonly toolACompareHref: string | null;
  readonly toolBCompareHref: string | null;
}) {
  if (!toolACompareHref && !toolBCompareHref) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-2xl font-semibold text-white">
        Compare the tools
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {toolACompareHref && (
          <CompareCard href={toolACompareHref} toolName={data.toolA} />
        )}
        {toolBCompareHref && (
          <CompareCard href={toolBCompareHref} toolName={data.toolB} />
        )}
      </div>
    </section>
  );
}
