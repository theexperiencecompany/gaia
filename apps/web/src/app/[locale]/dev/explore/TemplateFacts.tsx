"use client";

import { Avatar } from "@heroui/react";
import type { ReactNode } from "react";
import { LinkButton } from "@/components/shared/LinkButton";
import { appName, MARKETPLACE_PATH } from "../marketplace/appModel";

import { AppIcon } from "../tasks/AppIcon";
import { PropertyRow } from "../tasks/PropertyRow";
import { GaiaMark } from "../tasks/TaskIconTile";
import { WhenChip } from "../tasks/WhenChip";
import { creatorLabel, type Template } from "./templateModel";

/** A value in the facts that leads somewhere: an app's page, a category. */
function FactLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <LinkButton
      href={href}
      size="sm"
      variant="property"
      tone="bright"
      inset="tight"
      className="h-8 min-w-0 gap-1.5 text-sm"
    >
      {children}
    </LinkButton>
  );
}

/**
 * The template's facts in the Tasks sidebar's own rows: when it runs, the apps it
 * needs, who made it and where it is filed. Each row is a field of the template.
 */
export function TemplateFacts({
  template,
  categoryHref,
}: {
  template: Template;
  categoryHref: (category: string) => string;
}) {
  const { integration_ids, categories, creator } = template.data;
  return (
    <div>
      <PropertyRow label="When">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <WhenChip when={template.when} />
          {template.when.detail && (
            <span className="text-sm text-zinc-400">
              {template.when.detail}
            </span>
          )}
        </span>
      </PropertyRow>
      {integration_ids.length > 0 && (
        <PropertyRow label="Apps">
          <div className="-ml-2 flex flex-wrap">
            {integration_ids.map((app) => (
              <FactLink key={app} href={`${MARKETPLACE_PATH}/${app}`}>
                <AppIcon id={app} size={16} />
                {appName(app)}
              </FactLink>
            ))}
          </div>
        </PropertyRow>
      )}
      <PropertyRow label="Made by">
        <span className="flex items-center gap-2 text-sm text-zinc-200">
          {template.isByGaia ? (
            <GaiaMark size={18} />
          ) : (
            <Avatar className="size-[18px] shrink-0">
              {creator.avatar && <Avatar.Image src={creator.avatar} alt="" />}
              <Avatar.Fallback className="text-[10px]">
                {creator.name.slice(0, 1)}
              </Avatar.Fallback>
            </Avatar>
          )}
          {creatorLabel(template)}
        </span>
      </PropertyRow>
      {categories.length > 0 && (
        <PropertyRow label="Category">
          <div className="-ml-2 flex flex-wrap">
            {categories.map((category) => (
              <FactLink key={category} href={categoryHref(category)}>
                {category}
              </FactLink>
            ))}
          </div>
        </PropertyRow>
      )}
    </div>
  );
}
