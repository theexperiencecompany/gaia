import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import type { Postmark } from "@shared/api/generated";
import Image from "next/image";

import { postmarkBrief } from "../../utils/postmarkBrief";
import { BriefingFold } from "../BriefingFold";
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
      briefingId={postmark.briefing_id}
      brief={postmarkBrief(postmark)}
      renderTrigger={({ open, warm, isBusy }) => (
        <Tooltip
          content={<PostmarkCard postmark={postmark} />}
          classNames={{ content: "bg-transparent p-0 shadow-none" }}
          placement="bottom"
          closeDelay={0}
        >
          <Button
            disableRipple
            onPress={open}
            onPointerEnter={warm}
            onPointerDown={warm}
            onFocus={warm}
            aria-label={place}
            aria-busy={isBusy}
            className="group block h-auto w-full min-w-0 overflow-visible rounded-none bg-transparent p-0 data-[hover=true]:bg-transparent"
          >
            <span className="block aspect-[600/850] w-full transition-transform duration-200 ease-out group-data-[hover=true]:-translate-y-1 group-data-[hover=true]:-rotate-2 group-data-[pressed=true]:scale-95">
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

/** The cities still to collect as one small sheet of blank stamps: the whole set stays in view without the height. */
function StillToCollect({ count }: { count: number }) {
  // A blank has no city of its own; its place on the sheet is all that tells it apart.
  const blankKeys = Array.from(
    { length: count },
    (_, index) => `blank-${index}`,
  );
  const label = `${count} ${count === 1 ? "city" : "cities"} still to collect`;
  return (
    <div className="flex flex-col gap-2.5">
      <p aria-hidden className="text-xs text-zinc-500">
        Still to collect
      </p>
      <div role="img" aria-label={label} className="flex flex-wrap gap-1.5">
        {blankKeys.map((key) => (
          <span key={key} className="block aspect-[600/850] w-3">
            <StampBlank />
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * The album: the stamps collected so far in full, in arrival order, then every
 * city still to come as a small blank. Each stamp is captioned with its city
 * below sm, where there is no hover.
 */
export function StampCollection({ postmarks, total }: StampCollectionProps) {
  const remaining = Math.max(total - postmarks.length, 0);
  return (
    <div className="flex flex-col gap-6">
      {postmarks.length > 0 && (
        <ul
          aria-label="Stamp collection"
          className="grid grid-cols-3 gap-x-4 gap-y-5 sm:grid-cols-4 md:grid-cols-5"
        >
          {postmarks.map((postmark) => (
            <li key={postmark.city_slug}>
              <CollectedStamp postmark={postmark} />
            </li>
          ))}
        </ul>
      )}
      {remaining > 0 && <StillToCollect count={remaining} />}
    </div>
  );
}
