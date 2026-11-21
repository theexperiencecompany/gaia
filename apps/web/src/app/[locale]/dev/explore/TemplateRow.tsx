"use client";

import { LinkButton } from "@/components/shared/LinkButton";
import { IntegrationStack } from "../tasks/AppIcon";
import { TaskIconTile } from "../tasks/TaskIconTile";
import { WhenChip } from "../tasks/WhenChip";
import { creatorLabel, type Template } from "./templateModel";

export const EXPLORE_PATH = "/dev/explore";

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
      <div className="pointer-events-none relative flex gap-3.5 px-2 py-2.5">
        <span className="flex size-7 shrink-0 -translate-y-0.5 items-center justify-center">
          <TaskIconTile icon={template.icon} size={28} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-h-7 min-w-0 items-center gap-2">
            <p className="truncate text-[15px] leading-6 text-zinc-100">
              {title}
            </p>
            <IntegrationStack ids={integration_ids} size={15} />
            {!template.isByGaia && (
              <span className="shrink-0 truncate text-[13px] text-zinc-500">
                by {creatorLabel(template)}
              </span>
            )}
          </div>
          <p className="line-clamp-2 text-[13px] leading-5 text-zinc-500 sm:truncate">
            {summary}
          </p>
          <span className="mt-2 flex sm:hidden">
            <WhenChip when={template.when} />
          </span>
        </div>
        <span className="hidden h-7 shrink-0 items-center sm:flex">
          <WhenChip when={template.when} />
        </span>
      </div>
    </li>
  );
}
