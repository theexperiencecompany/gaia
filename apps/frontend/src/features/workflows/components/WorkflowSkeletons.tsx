import { Skeleton } from "@heroui/react";

export const WorkflowCardSkeleton = () => {
  return (
    <div className="relative z-[1] flex h-full min-h-fit w-full flex-col gap-2 rounded-3xl outline-1 bg-zinc-800 outline-zinc-800/70 p-4">
      <div className="flex items-start justify-between">
        <div className="flex min-h-8 items-center gap-2">
          <Skeleton className="h-8 w-8 rounded-lg" />
          <Skeleton className="h-8 w-8 rounded-lg" />
          <Skeleton className="h-8 w-8 rounded-lg" />
        </div>
      </div>

      <div>
        <Skeleton className="mb-2 h-6 w-3/4 rounded-lg" />
        <Skeleton className="h-4 w-full rounded-lg" />
        <Skeleton className="mt-1 h-4 w-2/3 rounded-lg" />
      </div>

      <div className="mt-auto">
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="space-y-1">
            <Skeleton className="h-3 w-20 rounded-lg" />
            <Skeleton className="h-3 w-16 rounded-lg" />
          </div>
          <Skeleton className="h-8 w-20 rounded-lg" />
        </div>
      </div>
    </div>
  );
};

export const WorkflowStepSkeleton = () => {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-zinc-800 p-3">
      <Skeleton className="h-8 w-8 flex-shrink-0 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    </div>
  );
};

export const WorkflowDetailSkeleton = () => {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="space-y-3">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>

      {/* Trigger info skeleton */}
      <div className="flex items-center gap-2">
        <Skeleton className="h-6 w-6 rounded-full" />
        <Skeleton className="h-5 w-32" />
      </div>

      {/* Steps skeleton */}
      <div className="space-y-3">
        <Skeleton className="h-6 w-40" />
        <WorkflowStepSkeleton />
        <WorkflowStepSkeleton />
        <WorkflowStepSkeleton />
      </div>
    </div>
  );
};

export const WorkflowListSkeleton = () => {
  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: just mapping empty skeletons
        <WorkflowCardSkeleton key={i} />
      ))}
    </div>
  );
};
