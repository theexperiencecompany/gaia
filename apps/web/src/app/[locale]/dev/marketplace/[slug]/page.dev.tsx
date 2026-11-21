"use client";

import { ArrowLeft01Icon, Tick02Icon } from "@icons";
import { notFound, useParams } from "next/navigation";
import { useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { LinkButton } from "@/components/shared/LinkButton";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { EXPLORE_PATH, TemplateRow } from "../../explore/TemplateRow";
import {
  CONNECTED_APPS,
  TEMPLATES,
  toTemplate,
} from "../../explore/templateModel";
import { PropertyRow } from "../../tasks/PropertyRow";
import { GaiaMark } from "../../tasks/TaskParts";
import TaskSection from "../../tasks/TaskSection";
import {
  categoryLabel,
  findApp,
  isByGaia,
  MARKETPLACE_PATH,
} from "../appModel";

/**
 * One app: what it is, what you can ask GAIA to do with it, and the templates
 * that use it. Connecting is the one action; the rest leads into Explore.
 */
export default function AppPage() {
  const { slug } = useParams<{ slug: string }>();
  const app = findApp(slug);
  const [isConnected, setIsConnected] = useState(
    app ? CONNECTED_APPS.includes(app.integrationId) : false,
  );
  if (!app) notFound();

  const templates = TEMPLATES.filter((item) =>
    item.integration_ids.includes(app.integrationId),
  ).map(toTemplate);
  const asks = app.content?.useCases ?? [];
  const tools = app.tools ?? [];

  return (
    <div className="dark min-h-dvh w-full bg-primary-bg text-zinc-100 selection:bg-[#00364b] selection:text-accent">
      <main className="mx-auto w-full max-w-[46rem] px-5 pb-32 pt-10">
        <LinkButton
          href={MARKETPLACE_PATH}
          size="sm"
          variant="quiet"
          tone="muted"
          hoverTone="bright"
          inset="tight"
          className="h-9 min-w-0 gap-1.5 text-sm"
        >
          <ArrowLeft01Icon className="size-4" />
          Marketplace
        </LinkButton>

        <header className="mt-8 px-2">
          <IntegrationIcon
            integrationId={app.integrationId}
            iconUrl={app.iconUrl}
            category={app.category}
            size={40}
          />
          <h1 className="mt-4 text-[28px] font-semibold leading-tight tracking-[-0.02em] text-white">
            {app.name}
          </h1>
          <p className="mt-1.5 text-[15px] leading-6 text-zinc-400">
            {app.description}
          </p>
          <GaiaButton
            size="sm"
            variant="tertiary"
            tone={isConnected ? "muted" : "strong"}
            isDisabled={isConnected}
            onPress={() => setIsConnected(true)}
            className="mt-6 h-9 gap-1.5 text-sm"
          >
            {isConnected && <Tick02Icon className="size-4" />}
            {isConnected
              ? "Connected"
              : isByGaia(app)
                ? `Connect ${app.name}`
                : "Add to GAIA"}
          </GaiaButton>
        </header>

        <div className="mt-8 px-2">
          <PropertyRow label="Made by">
            <span className="flex items-center gap-2 text-sm text-zinc-200">
              {isByGaia(app) && <GaiaMark size={18} />}
              {isByGaia(app) ? "GAIA" : (app.creator?.name ?? "Community")}
            </span>
          </PropertyRow>
          <PropertyRow label="Category">
            <span className="text-sm text-zinc-200">
              {categoryLabel(app.category)}
            </span>
          </PropertyRow>
        </div>

        {asks.length > 0 && (
          <section aria-labelledby="asks" className="mt-8 px-2">
            <h2 id="asks" className="text-[13px] font-medium text-zinc-500">
              What you can ask
            </h2>
            <ul className="mt-2 space-y-1.5">
              {asks.map((ask) => (
                <li key={ask} className="text-[15px] leading-6 text-zinc-200">
                  {ask}
                </li>
              ))}
            </ul>
          </section>
        )}

        {tools.length > 0 && (
          <section aria-labelledby="tools" className="mt-8 px-2">
            <h2 id="tools" className="text-[13px] font-medium text-zinc-500">
              What it can do
            </h2>
            <ul className="mt-2 space-y-3">
              {tools.map((tool) => (
                <li key={tool.name}>
                  <p className="font-mono text-sm text-zinc-200">{tool.name}</p>
                  {tool.description && (
                    <p className="mt-0.5 line-clamp-2 text-[13px] leading-5 text-zinc-500">
                      {tool.description}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {templates.length > 0 && (
          <div className="mt-14">
            <TaskSection
              id="templates"
              title={`Templates with ${app.name}`}
              count={templates.length}
              action={
                <LinkButton
                  href={`${EXPLORE_PATH}?app=${app.integrationId}`}
                  size="sm"
                  variant="quiet"
                  tone="faint"
                  hoverTone="bright"
                  inset="tight"
                  className="h-7 min-w-0 text-[13px]"
                >
                  Open in Explore
                </LinkButton>
              }
            >
              <ul>
                {templates.map((template) => (
                  <TemplateRow key={template.data.id} template={template} />
                ))}
              </ul>
            </TaskSection>
          </div>
        )}
      </main>
    </div>
  );
}
