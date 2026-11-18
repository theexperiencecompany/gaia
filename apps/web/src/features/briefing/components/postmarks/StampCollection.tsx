"use client";

import { Tooltip } from "@heroui/react";
import type { Postmark } from "@shared/api/generated";
import Image from "next/image";
import { Focusable } from "react-aria-components";

import { overlayVariants } from "@/components/shared/controlVariants";

import { useGridColumnCount } from "../../hooks/useGridColumnCount";
import { foldedBrief } from "../../utils/briefCard";
import { stampSheet } from "../../utils/stampSheet";
import { BriefingFold } from "../BriefingFold";
import { BriefTrigger } from "../BriefTrigger";
import { PostmarkCard } from "./PostmarkCard";
import { StampBlank } from "./StampBlank";

interface StampCollectionProps {
  postmarks: Postmark[];
  total: number;
}

/** One collected stamp: its city on hover, its brief readied as the pointer arrives, unfolding when pressed. */
function CollectedStamp({ postmark }: { postmark: Postmark }) {
  const place = `${postmark.city}, ${postmark.country}`;
  return (
    <BriefingFold
      briefingId={postmark.card.briefing_id}
      brief={foldedBrief(postmark.card)}
    >
      {(trigger) => (
        <Tooltip closeDelay={0}>
          <Focusable>
            <BriefTrigger
              trigger={trigger}
              onPress={() => trigger.open()}
              aria-label={place}
              className="group block h-auto w-full min-w-0 overflow-visible"
            >
              <span className="block aspect-[600/850] w-full transition-transform duration-200 ease-out group-hover:-translate-y-1 group-hover:-rotate-2 group-active:scale-95">
                <Image
                  src={postmark.stamp_url}
                  alt=""
                  width={200}
                  height={284}
                  className="h-full w-full object-contain drop-shadow-[0_6px_12px_rgb(0_0_0/0.45)]"
                />
              </span>
              <span className="mt-1.5 block truncate text-center text-xs text-zinc-400 sm:hidden">
                {postmark.city}
              </span>
            </BriefTrigger>
          </Focusable>
          <Tooltip.Content
            placement="bottom"
            className={overlayVariants({ surface: "bare" })}
          >
            <PostmarkCard postmark={postmark} />
          </Tooltip.Content>
        </Tooltip>
      )}
    </BriefingFold>
  );
}

/** A city still to collect, at a collected stamp's size; the last one counts every city the sheet leaves out. */
function BlankStamp({ counts }: { counts: number | null }) {
  return (
    <li aria-hidden className="relative block aspect-[600/850] w-full">
      <StampBlank />
      {counts !== null && (
        <span className="absolute inset-0 flex flex-col items-center justify-center px-2 text-center leading-tight">
          <span className="text-sm font-medium text-zinc-300 tabular-nums">
            +{counts}
          </span>{" "}
          <span className="text-xs text-balance text-zinc-500">
            more to unlock
          </span>
        </span>
      )}
    </li>
  );
}

/**
 * The album: the stamps collected so far in full, in arrival order, then blanks
 * only to finish their row (a full row when they end flush), the last blank
 * counting the rest. Each stamp is captioned with its city below sm, where
 * there is no hover.
 */
export function StampCollection({ postmarks, total }: StampCollectionProps) {
  const [gridRef, columns] = useGridColumnCount<HTMLUListElement>();
  const sheet =
    columns === null ? null : stampSheet(postmarks.length, total, columns);
  // A blank has no city of its own; its place on the sheet is all that tells it apart.
  const blankKeys = Array.from(
    { length: sheet?.blanks ?? 0 },
    (_, index) => `blank-${index}`,
  );
  return (
    <ul
      ref={gridRef}
      aria-label="Stamp collection"
      className="grid grid-cols-3 gap-x-4 gap-y-5 sm:grid-cols-4 md:grid-cols-5"
    >
      {postmarks.map((postmark) => (
        <li key={postmark.city_slug}>
          <CollectedStamp postmark={postmark} />
        </li>
      ))}
      {blankKeys.map((key, index) => (
        <BlankStamp
          key={key}
          counts={
            index === blankKeys.length - 1 ? (sheet?.lastCounts ?? null) : null
          }
        />
      ))}
    </ul>
  );
}
