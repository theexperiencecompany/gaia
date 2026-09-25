"use client";

import { Button } from "@heroui/button";
import { FullScreenIcon } from "@icons";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "@/components/shared/icons";
import { CursorArrow } from "@/features/chat/components/bubbles/bot/AgentCursor";
import { useImageDialog } from "@/stores/uiStore";

export interface RecapShot {
  index: number;
  url: string;
  /** What the agent was doing at this step ("Searching for …"). */
  caption?: string | null;
  /** Where the agent acted on this frame, as [x, y] fractions of the viewport. */
  point?: [number, number] | null;
}

/**
 * Navigable slideshow of a browser task's steps — the task prompt as a header,
 * the step screenshot with edge arrows, the current step's caption, a counter,
 * and a filmstrip. Shared by the chat task card and the settings history.
 */
export function RecapSlideshow({
  shots,
  title,
  enableKeyboard = false,
}: {
  shots: RecapShot[];
  title?: string;
  /** When true (e.g. the full-screen modal), left/right arrow keys navigate. */
  enableKeyboard?: boolean;
}) {
  const { openDialog } = useImageDialog();
  const [idx, setIdx] = useState(0);
  const count = shots.length;
  const go = useCallback(
    (i: number) => setIdx(Math.max(0, Math.min(count - 1, i))),
    [count],
  );

  useEffect(() => {
    if (!enableKeyboard) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") {
        setIdx((i) => Math.min(count - 1, i + 1));
        e.preventDefault();
      } else if (e.key === "ArrowLeft") {
        setIdx((i) => Math.max(0, i - 1));
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enableKeyboard, count]);

  if (count === 0) return null;
  const safeIdx = Math.min(idx, count - 1);
  const current = shots[safeIdx];
  const caption = current.caption?.trim();
  const atStart = safeIdx <= 0;
  const atEnd = safeIdx >= count - 1;

  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-900">
      {title && (
        <div className="border-b border-white/5 px-4 py-3">
          <p className="text-xs font-medium text-zinc-500">Task</p>
          <p className="mt-0.5 line-clamp-2 text-sm leading-snug text-zinc-200">
            {title}
          </p>
        </div>
      )}
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
          {current.point && (
            <span
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2"
              style={{
                left: `${current.point[0] * 100}%`,
                top: `${current.point[1] * 100}%`,
              }}
              aria-hidden
            >
              {/* A soft ring marks the spot; the arrow says it's the cursor. */}
              <span className="absolute -left-3.5 -top-3.5 size-7 rounded-full bg-[#00bbff]/25 ring-1 ring-[#00bbff]/50" />
              <CursorArrow />
            </span>
          )}
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

      <div className="px-4 py-3 text-center">
        {caption && (
          <p className="truncate text-sm font-medium text-zinc-100">
            {caption}
          </p>
        )}
        <p
          className={`text-xs tabular-nums text-zinc-500 ${caption ? "mt-0.5" : ""}`}
        >
          Step {safeIdx + 1} / {count}
        </p>
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
