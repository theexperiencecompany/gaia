"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Skeleton } from "@heroui/skeleton";

import { useBriefingsQuery } from "../hooks/useBriefingsQuery";
import { BriefingCard } from "./BriefingCard";

export interface BriefingArchiveProps {
  limit?: number;
  className?: string;
}

/** Browsable list of past briefings — each row expands into its full BriefingCard. */
export function BriefingArchive({
  limit = 30,
  className,
}: BriefingArchiveProps) {
  const { data: briefings, isLoading } = useBriefingsQuery(limit);

  if (isLoading) {
    return (
      <div className={className}>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  if (!briefings || briefings.length === 0) {
    return (
      <p
        className={
          className
            ? `${className} text-sm text-zinc-500`
            : "text-sm text-zinc-500"
        }
      >
        No past briefings yet.
      </p>
    );
  }

  return (
    <Accordion
      className={className}
      variant="splitted"
      selectionMode="multiple"
      itemClasses={{
        base: "bg-zinc-800 rounded-2xl",
        title: "text-sm font-medium text-zinc-100",
        subtitle: "text-xs text-zinc-500",
      }}
    >
      {briefings.map((briefing) => (
        <AccordionItem
          key={briefing.id}
          aria-label={briefing.payload.headline}
          title={briefing.payload.headline}
          subtitle={`${briefing.payload.kicker} — ${briefing.date}`}
        >
          <BriefingCard payload={briefing.payload} defaultCollapsed={false} />
        </AccordionItem>
      ))}
    </Accordion>
  );
}
