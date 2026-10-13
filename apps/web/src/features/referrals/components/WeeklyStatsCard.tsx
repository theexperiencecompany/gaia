"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import {
  CancelIcon,
  Copy01Icon,
  Download04Icon,
  Share08Icon,
  Tick02Icon,
} from "@icons";
import type { ReferralWeeklyCardResponse } from "@shared/api/generated";
import { RaisedButton } from "@/components/ui/raised-button";
import { cn } from "@/lib/utils";
import { useShareLink } from "../hooks/useShareLink";
import { weeklyImagePath } from "../hooks/useWeeklyCard";
import { REFERRAL_UI_COPY, WEEKLY_STATS_COPY } from "../referralCopy";
import { formatTimeSaved } from "../utils/timeSaved";

interface WeeklyStatsCardProps {
  card: ReferralWeeklyCardResponse;
  onDismiss: () => void;
  className?: string;
}

/** Last week's time back, and one way to share it. */
export function WeeklyStatsCard({
  card,
  onDismiss,
  className,
}: WeeklyStatsCardProps) {
  const time = formatTimeSaved(card.stats.minutes_saved);
  const { canShareNatively, copied, copy, shareNatively } = useShareLink({
    surface: "weekly_stats",
    copyVariant: card.copy_variant,
    url: card.share_link,
    text: WEEKLY_STATS_COPY.shareText(time),
    emailSubject: WEEKLY_STATS_COPY.emailSubject,
  });

  const shareIcon = canShareNatively ? (
    <Share08Icon width={16} height={16} />
  ) : copied ? (
    <Tick02Icon width={16} height={16} />
  ) : (
    <Copy01Icon width={16} height={16} />
  );

  return (
    <section
      className={cn(
        "flex w-full max-w-md flex-col gap-4 rounded-3xl bg-zinc-900/60 p-5 backdrop-blur-2xl",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-zinc-200">
          {WEEKLY_STATS_COPY.title}
        </h2>
        <Button
          isIconOnly
          aria-label={REFERRAL_UI_COPY.maybeLater}
          variant="light"
          size="sm"
          radius="full"
          className="-mr-1.5 text-zinc-500"
          onPress={onDismiss}
        >
          <CancelIcon width={14} height={14} />
        </Button>
      </div>
      <div className="flex flex-col gap-3 rounded-2xl bg-zinc-800/70 p-4">
        <p className="flex items-baseline gap-2">
          <span className="font-serif text-4xl text-zinc-100 tabular-nums">
            {time}
          </span>
          <span className="text-sm text-zinc-400">
            {WEEKLY_STATS_COPY.saved}
          </span>
        </p>
        <div className="flex gap-2">
          <Stat
            value={card.stats.actions}
            label={WEEKLY_STATS_COPY.actions(card.stats.actions)}
          />
          <Stat
            value={card.stats.workflow_runs}
            label={WEEKLY_STATS_COPY.workflowRuns(card.stats.workflow_runs)}
          />
        </div>
        <p className="text-xs text-zinc-500">{WEEKLY_STATS_COPY.estimate}</p>
      </div>
      <div className="flex gap-2">
        <RaisedButton
          color="#00bbff"
          className="flex-1 text-black!"
          onClick={canShareNatively ? shareNatively : copy}
        >
          {shareIcon}
          {canShareNatively
            ? WEEKLY_STATS_COPY.cta
            : copied
              ? REFERRAL_UI_COPY.copied
              : REFERRAL_UI_COPY.copyLink}
        </RaisedButton>
        <Button
          as={Link}
          href={weeklyImagePath(card)}
          download
          variant="flat"
          radius="full"
          startContent={<Download04Icon width={16} height={16} />}
        >
          {WEEKLY_STATS_COPY.saveImage}
        </Button>
      </div>
    </section>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <span className="rounded-full bg-zinc-900 px-3 py-1 text-xs text-zinc-300 tabular-nums">
      <span className="font-medium text-zinc-100">{value}</span> {label}
    </span>
  );
}
