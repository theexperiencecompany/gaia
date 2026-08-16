"use client";

import { Button } from "@heroui/button";
import { FullScreenIcon } from "@icons";
import Image from "next/image";
import { useCallback, useState } from "react";
import { ChevronLeft, ChevronRight } from "@/components/shared/icons";
import { useImageDialog } from "@/stores/uiStore";

export interface RecapShot {
  index: number;
  url: string;
}

/**
 * Navigable slideshow of a browser task's step screenshots — main frame with
 * edge arrows, a centered counter, and a filmstrip. Shared by the chat task
 * card (live steps) and the settings history (rebuilt from R2 URLs).
 */
export function RecapSlideshow({ shots }: { shots: RecapShot[] }) {
  const { openDialog } = useImageDialog();
  const [idx, setIdx] = useState(0);
  const count = shots.length;
  const go = useCallback(
    (i: number) => setIdx(Math.max(0, Math.min(count - 1, i))),
    [count],
  );

  if (count === 0) return null;
  const safeIdx = Math.min(idx, count - 1);
  const current = shots[safeIdx];
  const atStart = safeIdx <= 0;
  const atEnd = safeIdx >= count - 1;

  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-900">
      <div className="group relative bg-zinc-950">
        <button
          type="button"
          onClick={() => openDialog(current.url)}
          className="block w-full"
          aria-label={`Enlarge step ${current.index} screenshot`}
        >
          <Image
            src={current.url}
            alt={`Step ${current.index} screenshot`}
            width={1280}
            height={720}
            className="h-auto w-full"
            unoptimized
          />
          <span className="pointer-events-none absolute right-2.5 top-2.5 flex size-7 items-center justify-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur-sm transition group-hover:opacity-100">
            <FullScreenIcon className="size-3.5" />
          </span>
        </button>
        {!atStart && (
          <Button
            isIconOnly
            radius="full"
            size="sm"
            className="absolute left-2.5 top-1/2 -translate-y-1/2 bg-black/45 text-white opacity-0 backdrop-blur-sm transition group-hover:opacity-100 data-[hover=true]:bg-black/65"
            aria-label="Previous step"
            onPress={() => go(safeIdx - 1)}
          >
            <ChevronLeft className="size-4" />
          </Button>
        )}
        {!atEnd && (
          <Button
            isIconOnly
            radius="full"
            size="sm"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 bg-black/45 text-white opacity-0 backdrop-blur-sm transition group-hover:opacity-100 data-[hover=true]:bg-black/65"
            aria-label="Next step"
            onPress={() => go(safeIdx + 1)}
          >
            <ChevronRight className="size-4" />
          </Button>
        )}
      </div>

      <div className="flex items-center justify-center gap-2 py-2.5">
        <span className="text-xs font-medium text-zinc-400">
          Step {current.index}
        </span>
        <span className="size-1 rounded-full bg-zinc-600" />
        <span className="text-xs tabular-nums text-zinc-500">
          <span className="text-zinc-200">{safeIdx + 1}</span> / {count}
        </span>
      </div>

      {count > 1 && (
        <div className="flex gap-2 overflow-x-auto border-t border-white/5 p-2.5">
          {shots.map((s, i) => (
            <button
              key={`recap-thumb-${s.index}`}
              type="button"
              onClick={() => go(i)}
              aria-label={`Go to step ${s.index}`}
              className={`shrink-0 overflow-hidden rounded-lg transition ${
                i === safeIdx
                  ? "opacity-100 ring-2 ring-[#00bbff]"
                  : "opacity-60 ring-1 ring-white/10 hover:opacity-100 hover:ring-white/25"
              }`}
            >
              <Image
                src={s.url}
                alt=""
                width={96}
                height={54}
                className="h-[52px] w-[92px] object-cover"
                unoptimized
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
