"use client";

import type { ReactNode } from "react";

import { LinkButton } from "@/components/shared/LinkButton";
import { cn } from "@/lib/utils";
import { IntegrationStack } from "../tasks/AppIcon";
import { TaskIconTile } from "../tasks/TaskIconTile";
import type { TaskWhen } from "../tasks/taskModel";
import { WhenChip } from "../tasks/WhenChip";
import { creatorLabel, type Template } from "./templateModel";

export const EXPLORE_PATH = "/dev/explore";

/**
 * What a template row shows, as Explore lists it and as Publish previews it.
 * Narrow places (a phone, the sidebar) put the when-chip under the line.
 */
export function TemplateRowBody({
  icon,
  title,
  apps,
  byline,
  summary,
  when,
  isNarrow = false,
}: {
  icon?: Template["icon"];
  title: string;
  apps: string[];
  /** The maker, only when it is not GAIA. */
  byline?: string;
  summary: ReactNode;
  when: TaskWhen;
  isNarrow?: boolean;
}) {
  return (
    <div className="pointer-events-none relative flex gap-3.5 px-2 py-2.5">
      <span className="flex size-7 shrink-0 -translate-y-0.5 items-center justify-center">
        <TaskIconTile icon={icon} size={28} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-h-7 min-w-0 items-center gap-2">
          <p className="truncate text-[15px] leading-6 text-zinc-100">
            {title}
          </p>
          <IntegrationStack ids={apps} size={15} />
          {byline && (
            <span className="shrink-0 truncate text-[13px] text-zinc-500">
              by {byline}
            </span>
          )}
        </div>
        <p
          className={cn(
            "line-clamp-2 text-[13px] leading-5 text-zinc-500",
            !isNarrow && "sm:truncate",
          )}
        >
          {summary}
        </p>
        <span className={cn("mt-2 flex", !isNarrow && "sm:hidden")}>
          <WhenChip when={when} />
        </span>
      </div>
      {!isNarrow && (
        <span className="hidden h-7 shrink-0 items-center sm:flex">
          <WhenChip when={when} />
        </span>
      )}
    </div>
  );
}

/**
 * A template the way a task row reads: its tile, its name and the apps it needs,
 * then the one line that says what you get, and when it runs on the right.
 */
export function TemplateRow({ template }: { template: Template }) {
  const { title, summary, slug, integration_ids } = template.data;
  return (
    <li className="relative">
      <LinkButton
        href={`${EXPLORE_PATH}/${slug}`}
        aria-label={title}
        variant="row"
        shape="md"
        inset="none"
        className="absolute inset-0 h-full w-full min-w-0"
      />
      <TemplateRowBody
        icon={template.icon}
        title={title}
        apps={integration_ids}
        byline={template.isByGaia ? undefined : creatorLabel(template)}
        summary={summary}
        when={template.when}
      />
    </li>
  );
}
