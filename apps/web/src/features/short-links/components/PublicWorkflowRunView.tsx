"use client";

import { useLocale } from "next-intl";
import { useMemo } from "react";

import { RichContentRenderer } from "@/features/chat/components/interface/RichContentRenderer";
import { ExecutionStatusBadge } from "@/features/workflows/components/ExecutionStatusBadge";
import type { PublicWorkflowRun } from "@/types/features/shortLinkTypes";

export function PublicWorkflowRunView({ view }: { view: PublicWorkflowRun }) {
  const locale = useLocale();
  const dateFormat = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }),
    [locale],
  );

  return (
    <article className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <ExecutionStatusBadge status={view.status} />
          <span className="text-xs text-zinc-500">
            {dateFormat.format(new Date(view.started_at))} UTC
          </span>
        </div>
        <h1 className="text-2xl font-medium text-white">
          {view.workflow_title}
        </h1>
      </div>
      <div className="rounded-2xl bg-zinc-800 p-4">
        {view.status === "running" ? (
          <p className="text-sm text-zinc-400">
            This run is still finishing. Check back in a moment.
          </p>
        ) : view.summary ? (
          <RichContentRenderer content={view.summary} className="text-base" />
        ) : (
          <p className="text-sm text-zinc-500">
            This run didn't record a summary.
          </p>
        )}
      </div>
    </article>
  );
}
