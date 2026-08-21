"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Modal, ModalBody, ModalContent, useDisclosure } from "@heroui/modal";
import { Fire02Icon, Share08Icon } from "@icons";
import type { ActivityDay, UsageActivity } from "@shared/types";
import { formatCompactNumber, formatDateUTC } from "@shared/utils";
import confetti from "canvas-confetti";
import Image from "next/image";
import {
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";
import { shareActivityCard } from "./shareActivityCard";
import { buildTweetText, openTweetIntent } from "./shareTweet";

const ACCENT = "#00bbff";
const EMPTY = "#27272a";

/** Five-step activity ramp (empty → full accent). Cell coloring and the
 *  Less/More legend both read this so they can never disagree. */
const INTENSITY_RAMP = [
  EMPTY,
  "rgba(0,187,255,0.3)",
  "rgba(0,187,255,0.52)",
  "rgba(0,187,255,0.78)",
  ACCENT,
] as const;

// Rendered medal art (transparent PNGs). Gold + diamond ship as assets; silver, bronze
// and locked are the gold medal recolored at render time via CSS filters.
const TIERS = {
  diamond: {
    label: "Top 0.1%",
    src: "/badges/diamond.png",
    filter: "",
    confetti: ["#bfeaf5", "#5bc7e0", "#2b9fc4"],
  },
  gold: {
    label: "Top 1%",
    src: "/badges/gold.png",
    filter: "",
    confetti: ["#ffe9a8", "#f6c863", "#e0a020"],
  },
  silver: {
    label: "Top 10%",
    src: "/badges/gold.png",
    filter: "grayscale(1) brightness(1.12) contrast(0.97)",
    confetti: ["#f2f4f7", "#c8cdd6", "#9aa1ad"],
  },
  bronze: {
    label: "Top 25%",
    src: "/badges/gold.png",
    filter:
      "sepia(1) saturate(2.2) hue-rotate(-26deg) brightness(0.8) contrast(1.05)",
    confetti: ["#f0c89a", "#c9884e", "#9a5f2c"],
  },
  locked: {
    label: "Top 25%",
    src: "/badges/gold.png",
    filter: "grayscale(1) brightness(0.5) blur(1.5px)",
    confetti: ["#52525b", "#3f3f46", "#71717a"],
  },
} as const;

interface Cell {
  date: string;
  count: number | null;
  /** Prebuilt hover/aria label ("N actions · Mon, Jul 5"); empty for padding cells. */
  label: string;
}

/** The hover/aria line for one cell. Tokens only join it when there are any —
 *  a quiet day should not read "0 tokens", and days that predate token
 *  accounting have none to report. */
function cellLabel(
  date: string,
  day: ActivityDay | undefined,
  count: number | null,
): string {
  if (count === null) return "";
  const tokens = day?.tokens ?? 0;
  return [
    `${count} ${count === 1 ? "action" : "actions"}`,
    tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : null,
    formatDateUTC(date, "weekday"),
  ]
    .filter(Boolean)
    .join(" · ");
}

function intensity(count: number | null, max: number): string {
  if (count === null) return "transparent";
  if (count === 0) return INTENSITY_RAMP[0];
  const r = count / max;
  if (r < 0.25) return INTENSITY_RAMP[1];
  if (r < 0.5) return INTENSITY_RAMP[2];
  if (r < 0.75) return INTENSITY_RAMP[3];
  return INTENSITY_RAMP[4];
}

function shareToX(activity: UsageActivity) {
  const label = activity.tier ? TIERS[activity.tier].label : null;
  openTweetIntent(buildTweetText(label, activity.streak));
}

/** Ranked users share a rendered image card; unranked fall back to plain text. */
async function shareActivity(activity: UsageActivity) {
  if (!activity.tier) {
    shareToX(activity);
    return;
  }
  await shareActivityCard(activity, TIERS[activity.tier], intensity);
}

function Medal({
  tier,
  className,
}: {
  tier: keyof typeof TIERS;
  className?: string;
}) {
  const t = TIERS[tier];
  return (
    <Image
      src={t.src}
      alt=""
      aria-hidden
      draggable={false}
      width={96}
      height={96}
      // Small static local asset re-tinted via CSS filter — optimization would
      // only re-encode the tint's source pixels.
      unoptimized
      className={cn("object-contain", className)}
      style={t.filter ? { filter: t.filter } : undefined}
    />
  );
}

function fireBadgeConfetti(tier: keyof typeof TIERS) {
  const base: confetti.Options = {
    spread: 78,
    startVelocity: 42,
    ticks: 160,
    zIndex: 9999,
    colors: [...TIERS[tier].confetti],
  };
  confetti({ ...base, particleCount: 70, origin: { x: 0.5, y: 0.4 } });
  window.setTimeout(
    () =>
      confetti({
        ...base,
        particleCount: 45,
        angle: 60,
        origin: { x: 0.15, y: 0.5 },
      }),
    130,
  );
  window.setTimeout(
    () =>
      confetti({
        ...base,
        particleCount: 45,
        angle: 120,
        origin: { x: 0.85, y: 0.5 },
      }),
    130,
  );
}

/** The award / percentile bento — square, sits beside the day-by-day chart.
 *  Earned badges open a celebratory modal (large medal, share, confetti). */
export function ActivityBadge({
  tier,
  activity,
}: {
  tier: UsageActivity["tier"];
  activity: UsageActivity;
}) {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();

  useEffect(() => {
    if (isOpen && tier) fireBadgeConfetti(tier);
  }, [isOpen, tier]);

  if (!tier) {
    return (
      <div className="flex w-44 shrink-0 flex-col items-center justify-start gap-1 rounded-2xl bg-zinc-900/60 p-4 text-center">
        <Medal tier="locked" className="size-28 opacity-80" />
        <p className="mt-1 text-sm font-semibold text-zinc-400">Top 25%</p>
        <p className="text-[11px] leading-tight text-zinc-600">
          Keep using GAIA to earn your first badge
        </p>
      </div>
    );
  }

  const t = TIERS[tier];
  return (
    <>
      <Button
        onPress={onOpen}
        disableRipple
        className="flex h-auto w-44 shrink-0 flex-col items-center justify-start gap-1 rounded-2xl bg-zinc-900/60 p-4 text-center transition-colors data-[hover=true]:bg-zinc-800/70"
      >
        <Medal tier={tier} className="size-28" />
        <p className="mt-1 text-lg font-semibold text-white">{t.label}</p>
        <p className="text-[11px] leading-tight text-zinc-500">
          of GAIA users by activity
        </p>
      </Button>

      <Modal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        size="sm"
        placement="center"
        backdrop="blur"
      >
        <ModalContent className="bg-zinc-900">
          <ModalBody className="items-center gap-0 px-8 py-10 text-center">
            <Medal
              tier={tier}
              className="size-44 drop-shadow-[0_10px_35px_rgba(0,0,0,0.55)]"
            />
            <p className="mt-6 text-2xl font-semibold text-white">{t.label}</p>
            <p className="mt-1 text-sm text-zinc-400">
              of GAIA users by activity
            </p>
            <div className="mt-5 flex items-center gap-5 text-sm text-zinc-500">
              <span>
                <span className="font-semibold text-zinc-200">
                  {formatCompactNumber(activity.total)}
                </span>{" "}
                actions
              </span>
              <span>
                <span className="font-semibold text-zinc-200">
                  {activity.streak}
                </span>
                -day streak
              </span>
            </div>
            <Button
              className="mt-7 font-medium"
              color="primary"
              radius="full"
              startContent={<Share08Icon size={16} />}
              onPress={() => void shareActivity(activity)}
            >
              Share
            </Button>
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  );
}

export function UsageHeatmap({ activity }: { activity: UsageActivity }) {
  const gridRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{
    label: string;
    x: number;
    y: number;
  } | null>(null);

  const { columns, max } = useMemo(() => {
    const days = activity.days;
    if (days.length < 14) return { columns: [] as Cell[][], max: 1 };
    const byDate = new Map(days.map((d) => [d.date, d]));
    const first = new Date(`${days[0].date}T00:00:00Z`);
    const last = new Date(`${days[days.length - 1].date}T00:00:00Z`);
    const cursor = new Date(first);
    cursor.setUTCDate(cursor.getUTCDate() - cursor.getUTCDay());
    const columns: Cell[][] = [];
    while (cursor <= last) {
      const col: Cell[] = [];
      for (let wd = 0; wd < 7; wd++) {
        const key = cursor.toISOString().slice(0, 10);
        const inRange = cursor >= first && cursor <= last;
        const day = inRange ? byDate.get(key) : undefined;
        const count = inRange ? (day?.count ?? 0) : null;
        col.push({ date: key, count, label: cellLabel(key, day, count) });
        cursor.setUTCDate(cursor.getUTCDate() + 1);
      }
      columns.push(col);
    }
    return { columns, max: Math.max(1, ...days.map((d) => d.count)) };
  }, [activity]);

  // One shared hover label positioned over the hovered cell — a grid of ~365
  // per-cell Tooltips is needlessly heavy for a single floating label.
  const showTip = useCallback((e: MouseEvent<HTMLDivElement>, cell: Cell) => {
    const grid = gridRef.current;
    if (!grid || !cell.label) return;
    const cr = e.currentTarget.getBoundingClientRect();
    const gr = grid.getBoundingClientRect();
    setTip({
      label: cell.label,
      x: cr.left - gr.left + cr.width / 2,
      y: cr.top - gr.top - 4,
    });
  }, []);

  const hideTip = useCallback(() => setTip(null), []);

  if (!columns.length) return null;

  return (
    <section className="rounded-2xl bg-zinc-900/60 p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="text-base font-semibold text-white">
            GAIA&apos;s activity
          </p>
          <p className="text-[13px] text-zinc-500">
            <span className="font-medium tabular-nums text-zinc-300">
              {formatCompactNumber(activity.total)}
            </span>{" "}
            actions
          </p>
          {activity.streak > 0 && (
            <Chip
              size="sm"
              variant="flat"
              radius="full"
              classNames={{
                base: "h-6 bg-orange-500/15",
                content:
                  "flex items-center gap-1 px-2 text-xs font-medium text-orange-400",
              }}
            >
              <Fire02Icon size={13} />
              {activity.streak}-day streak
            </Chip>
          )}
        </div>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          className="shrink-0 text-zinc-400 data-[hover=true]:text-zinc-100"
          aria-label="Share on X"
          onPress={() => void shareActivity(activity)}
        >
          <Share08Icon size={16} />
        </Button>
      </div>

      <div className="flex gap-[3px]">
        {columns.map((col, ci) => {
          const m = new Date(`${col[0].date}T00:00:00Z`).getUTCMonth();
          const prev =
            ci > 0
              ? new Date(`${columns[ci - 1][0].date}T00:00:00Z`).getUTCMonth()
              : -1;
          return (
            <div
              key={col[0].date}
              className="flex-1 text-[9px] leading-none text-zinc-500"
            >
              <span className="whitespace-nowrap">
                {m !== prev ? formatDateUTC(col[0].date, "month") : ""}
              </span>
            </div>
          );
        })}
      </div>
      <div ref={gridRef} className="relative mt-1 flex gap-[3px]">
        {columns.map((col) => (
          <div key={col[0].date} className="flex flex-1 flex-col gap-[3px]">
            {col.map((cell) =>
              cell.count === null ? (
                // Padding day outside the range — no data, no hover label.
                <div key={cell.date} className="aspect-square rounded-[2px]" />
              ) : (
                <div
                  key={cell.date}
                  role="img"
                  aria-label={cell.label}
                  className="aspect-square rounded-[2px]"
                  style={{ backgroundColor: intensity(cell.count, max) }}
                  onMouseEnter={(e) => showTip(e, cell)}
                  onMouseLeave={hideTip}
                />
              ),
            )}
          </div>
        ))}
        {tip && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-zinc-800 px-2 py-1 text-xs font-medium text-zinc-100 shadow-xl"
            style={{ left: tip.x, top: tip.y }}
          >
            {tip.label}
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center justify-end gap-1.5 text-[11px] text-zinc-500">
        <span>Less</span>
        {INTENSITY_RAMP.map((c) => (
          <div
            key={c}
            className="size-2.5 rounded-[2px]"
            style={{ backgroundColor: c }}
          />
        ))}
        <span>More</span>
      </div>
    </section>
  );
}
