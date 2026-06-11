"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import {
  ArrowDown01Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  BookOpen01Icon,
} from "@icons";
import { addDays, format, isToday, parseISO, subDays } from "date-fns";
import { useEffect, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEpisode } from "@/features/memory/api/types";
import { MemoryEmptyState } from "@/features/memory/components/MemoryEmptyState";
import { JOURNAL_RANGE_DAYS } from "@/features/memory/constants";

const ISO_DATE_FORMAT = "yyyy-MM-dd";

export function MemoryTimeline() {
  const [rangeEnd, setRangeEnd] = useState(() => new Date());
  const [episodes, setEpisodes] = useState<MemoryEpisode[]>([]);
  const [loading, setLoading] = useState(true);

  const rangeStart = subDays(rangeEnd, JOURNAL_RANGE_DAYS - 1);
  const atToday = isToday(rangeEnd);

  useEffect(() => {
    let cancelled = false;
    const fetchEpisodes = async () => {
      setLoading(true);
      try {
        const response = await memoryApi.getEpisodes(
          format(subDays(rangeEnd, JOURNAL_RANGE_DAYS - 1), ISO_DATE_FORMAT),
          format(rangeEnd, ISO_DATE_FORMAT),
        );
        if (!cancelled) {
          setEpisodes(
            [...(response.episodes ?? [])].sort((a, b) =>
              b.date.localeCompare(a.date),
            ),
          );
        }
      } catch {
        if (!cancelled) setEpisodes([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchEpisodes();
    return () => {
      cancelled = true;
    };
  }, [rangeEnd]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-400">
          {format(rangeStart, "MMM d")} to {format(rangeEnd, "MMM d, yyyy")}
        </p>
        <div className="flex gap-1">
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            className="rounded-xl"
            aria-label="Previous two weeks"
            onPress={() => setRangeEnd(subDays(rangeEnd, JOURNAL_RANGE_DAYS))}
          >
            <ArrowLeft01Icon className="size-4" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            className="rounded-xl"
            aria-label="Next two weeks"
            isDisabled={atToday}
            onPress={() => {
              const next = addDays(rangeEnd, JOURNAL_RANGE_DAYS);
              setRangeEnd(next > new Date() ? new Date() : next);
            }}
          >
            <ArrowRight01Icon className="size-4" />
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full rounded-2xl" />
          <Skeleton className="h-28 w-full rounded-2xl" />
        </div>
      ) : episodes.length === 0 ? (
        <MemoryEmptyState
          icon={BookOpen01Icon}
          title="No journal entries in this range"
          description="GAIA writes a short journal line for each conversation. Days fill in as you talk."
        />
      ) : (
        <div className="space-y-2">
          {episodes.map((episode, index) => (
            <EpisodeCard
              key={episode.date}
              episode={episode}
              defaultOpen={index === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function EpisodeCard({
  episode,
  defaultOpen,
}: {
  episode: MemoryEpisode;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const date = parseISO(episode.date);
  const hasContent = episode.summary || episode.entries.length > 0;

  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-white/5"
      >
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-white">
            {format(date, "EEEE, MMM d")}
          </p>
          {isToday(date) && <span className="text-xs text-primary">Today</span>}
        </div>
        {hasContent &&
          (open ? (
            <ArrowUp01Icon className="size-4 shrink-0 text-zinc-500" />
          ) : (
            <ArrowDown01Icon className="size-4 shrink-0 text-zinc-500" />
          ))}
      </button>

      {open && hasContent && (
        <div className="px-5 pb-4">
          {episode.summary && (
            <p className="text-sm text-zinc-400">{episode.summary}</p>
          )}

          {episode.entries.length > 0 && (
            <div className="mt-2 space-y-1.5">
              {episode.entries.map((entry) => (
                <div
                  key={`${entry.time}-${entry.text}`}
                  className="flex items-baseline gap-3"
                >
                  <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                    {entry.time}
                  </span>
                  <p className="text-sm text-zinc-300">{entry.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
