import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import type { Postmark } from "@shared/api/generated";
import Image from "next/image";

import { cn } from "@/lib/utils";
import { BriefingFold } from "../BriefingFold";
import { PostmarkCard } from "./PostmarkCard";
import { StampBlank } from "./StampBlank";

interface StampCollectionProps {
  postmarks: Postmark[];
  total: number;
}

// The stamp art's own proportions, so a blank and a stamp occupy the same cell.
const STAMP_SLOT = "aspect-[600/850] w-full";

/** One collected stamp: its city on hover, and the brief it came on unfolding when pressed. */
function CollectedStamp({ postmark }: { postmark: Postmark }) {
  const place = `${postmark.city}, ${postmark.country}`;
  return (
    <BriefingFold
      briefingId={postmark.briefing_id}
      brief={{ headline: `Your brief from ${postmark.city}` }}
      renderTrigger={({ open, isBusy }) => (
        <Tooltip
          content={<PostmarkCard postmark={postmark} />}
          classNames={{ content: "bg-transparent p-0 shadow-none" }}
          placement="bottom"
          closeDelay={0}
        >
          <Button
            disableRipple
            onPress={open}
            aria-label={place}
            aria-busy={isBusy}
            className="group block h-auto w-full min-w-0 overflow-visible rounded-none bg-transparent p-0 data-[hover=true]:bg-transparent"
          >
            <span
              className={cn(
                STAMP_SLOT,
                "block transition-transform duration-200 ease-out group-data-[hover=true]:-translate-y-1 group-data-[hover=true]:-rotate-2 group-data-[pressed=true]:scale-95",
              )}
            >
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
          </Button>
        </Tooltip>
      )}
    />
  );
}

/**
 * The album, every city in it: collected stamps first in arrival order, in
 * colour, then a blank in the stamp's shape for each city still to come. Each
 * stamp is captioned with its city below sm, where there is no hover.
 */
export function StampCollection({ postmarks, total }: StampCollectionProps) {
  const remaining = Math.max(total - postmarks.length, 0);
  // A blank has no city of its own; its place in the album is all that tells it apart.
  const blankKeys = Array.from(
    { length: remaining },
    (_, index) => `blank-${index}`,
  );
  return (
    <ul
      aria-label="Stamp collection"
      className="grid grid-cols-3 gap-x-4 gap-y-5 sm:grid-cols-4 md:grid-cols-5"
    >
      {postmarks.map((postmark) => (
        <li key={postmark.city_slug}>
          <CollectedStamp postmark={postmark} />
        </li>
      ))}
      {blankKeys.map((key) => (
        <li key={key} aria-hidden className={STAMP_SLOT}>
          <StampBlank />
        </li>
      ))}
      {remaining > 0 && (
        <li className="sr-only">
          {remaining} {remaining === 1 ? "city" : "cities"} still to collect
        </li>
      )}
    </ul>
  );
}
