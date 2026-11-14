import { Skeleton } from "@heroui/react";

/** Loading placeholder for a skills list / folder list. */
export function SkillListSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-16 w-full rounded-2xl" />
      <Skeleton className="h-16 w-full rounded-2xl" />
      <Skeleton className="h-16 w-full rounded-2xl" />
    </div>
  );
}
