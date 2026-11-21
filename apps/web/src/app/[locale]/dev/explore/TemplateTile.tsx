"use client";

import { LinkButton } from "@/components/shared/LinkButton";
import { IntegrationStack, TaskIconTile, WhenChip } from "../tasks/TaskParts";
import { EXPLORE_PATH } from "./TemplateRow";
import { creatorLabel, type Template } from "./templateModel";

/** Sketch B: a template as a flat cell in a two-column index; no border, a fill only on hover. */
export function TemplateTile({ template }: { template: Template }) {
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
      <div className="pointer-events-none relative flex h-full flex-col gap-3 p-3">
        <div className="flex items-center justify-between">
          <TaskIconTile icon={template.icon} size={32} />
          <IntegrationStack ids={integration_ids} size={16} />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="truncate text-[15px] leading-6 text-zinc-100">
            {title}
          </p>
          <p className="line-clamp-2 text-[13px] leading-5 text-zinc-500">
            {summary}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <WhenChip when={template.when} />
          {!template.isByGaia && (
            <span className="truncate text-[13px] text-zinc-500">
              by {creatorLabel(template)}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}
