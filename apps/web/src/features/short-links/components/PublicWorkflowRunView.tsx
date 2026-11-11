"use client";

import { useLocale } from "next-intl";
import { useMemo, useSyncExternalStore } from "react";

import { RichContentRenderer } from "@/features/chat/components/interface/RichContentRenderer";
import { ExecutionStatusBadge } from "@/features/workflows/components/ExecutionStatusBadge";
import type { PublicWorkflowRun } from "@/types/features/shortLinkTypes";

const subscribeNever = () => () => undefined;

export function PublicWorkflowRunView({ view }: { view: PublicWorkflowRun }) {
  const locale = useLocale();
  const dateFormat = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    [locale],
  );
  // The reader's own time zone exists only in the browser: the server renders
  // no label and the client fills it in on hydration, so the two never disagree.
  const startedLabel = useSyncExternalStore(
    subscribeNever,
    () => dateFormat.format(new Date(view.started_at)),
    () => null,
  );

  return (
    <article className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <ExecutionStatusBadge status={view.status} />
          <time dateTime={view.started_at} className="text-xs text-zinc-500">
            {startedLabel}
          </time>
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
