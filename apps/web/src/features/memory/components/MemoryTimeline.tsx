"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { ArrowLeft01Icon, ArrowRight01Icon, BookOpen01Icon } from "@icons";
import { addDays, format, isToday, parseISO, subDays } from "date-fns";
import { useEffect, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEpisode } from "@/features/memory/api/types";
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
          {format(rangeStart, "MMM d")} – {format(rangeEnd, "MMM d, yyyy")}
        </p>
        <div className="flex gap-1">
          <Button
            isIconOnly
            size="sm"
            variant="flat"
            aria-label="Previous two weeks"
            onPress={() => setRangeEnd(subDays(rangeEnd, JOURNAL_RANGE_DAYS))}
          >
            <ArrowLeft01Icon className="size-4" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="flat"
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
        <div className="flex h-48 flex-col items-center justify-center gap-1 text-zinc-500">
          <BookOpen01Icon className="mb-2 size-8 opacity-40" />
          <p className="text-sm">No journal entries in this range</p>
          <p className="text-xs">
            GAIA writes a short journal line for each conversation — days fill
            in as you talk
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {episodes.map((episode) => (
            <EpisodeCard key={episode.date} episode={episode} />
          ))}
        </div>
      )}
    </div>
  );
}

function EpisodeCard({ episode }: { episode: MemoryEpisode }) {
  const date = parseISO(episode.date);

  return (
    <div className="rounded-2xl bg-zinc-900/60 px-5 py-4">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-white">
          {format(date, "EEEE, MMM d")}
        </p>
        {isToday(date) && <span className="text-xs text-primary">Today</span>}
      </div>

      {episode.summary && (
        <p className="mt-2 text-sm text-zinc-400">{episode.summary}</p>
      )}

      {episode.entries.length > 0 && (
        <div className="mt-3 space-y-1.5">
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
  );
}
