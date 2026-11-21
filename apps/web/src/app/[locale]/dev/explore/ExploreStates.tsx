"use client";

import { Skeleton } from "@heroui/react";
import type { ComponentType, ReactNode } from "react";

/** Placeholder rows with the exact geometry of TemplateRow, so nothing moves when data lands. */
export function LoadingRows({ count = 6 }: { count?: number }) {
  return (
    <ul aria-busy="true" aria-label="Loading templates">
      {Array.from({ length: count }, (_, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity
        <li key={index} className="flex gap-3.5 px-2 py-2.5">
          <Skeleton className="size-7 shrink-0 rounded-lg" />
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-7 items-center">
              <Skeleton className="h-3.5 w-40 rounded-md" />
            </div>
            <div className="flex h-5 items-center">
              <Skeleton className="h-3 w-72 max-w-full rounded-md" />
            </div>
          </div>
          <Skeleton className="hidden h-6 w-28 shrink-0 rounded-lg sm:block" />
        </li>
      ))}
    </ul>
  );
}

/** A centred note in place of the list: an icon, one sentence, and at most one way out. */
export function EmptyState({
  Icon,
  title,
  detail,
  action,
}: {
  Icon: ComponentType<{ className?: string }>;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-20 text-center">
      <Icon className="size-6 text-zinc-600" />
      <p className="mt-3 text-[15px] text-zinc-200">{title}</p>
      {detail && (
        <p className="mt-1 max-w-sm text-[13px] leading-5 text-zinc-500">
          {detail}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
