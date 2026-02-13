"use client";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { type ReactNode, useState } from "react";

import { useHoverSummary } from "@/features/mail/hooks/useHoverSummary";

interface EmailHoverSummaryProps {
  emailId: string;
  subject: string;
  children: ReactNode;
}

export function EmailHoverSummary({
  emailId,
  subject,
  children,
}: EmailHoverSummaryProps) {
  const [shouldFetch, setShouldFetch] = useState(false);
  const { data, isLoading } = useHoverSummary(emailId, shouldFetch);

  return (
    <Tooltip
      delay={500}
      closeDelay={0}
      onOpenChange={(isOpen) => {
        if (isOpen) setShouldFetch(true);
      }}
      content={
        <div className="flex w-[300px] flex-col gap-1 p-2">
          <div className="text-sm leading-tight font-medium">{subject}</div>
          {isLoading ? (
            <div className="flex flex-col gap-1">
              <Skeleton className="h-3 w-full rounded" />
              <Skeleton className="h-3 w-3/4 rounded" />
            </div>
          ) : data?.summary ? (
            <div className="text-xs text-foreground-500">{data.summary}</div>
          ) : null}
        </div>
      }
      color="foreground"
      radius="sm"
    >
      <span>{children}</span>
    </Tooltip>
  );
}
