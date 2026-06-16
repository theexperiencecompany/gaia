"use client";

import { Avatar } from "@heroui/avatar";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Input } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import {
  CheckmarkCircle02Icon,
  CopyIcon,
  GiftIcon,
  Link01Icon,
  Mail01Icon,
  MailAdd01Icon,
  PencilEdit01Icon,
  SentIcon,
  TwitterIcon,
  WhatsappIcon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import * as m from "motion/react-m";
import { type KeyboardEvent, useState } from "react";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { useInviteFriends, useReferralOverview } from "../hooks/useReferrals";
import type {
  EarnedReward,
  FriendReferral,
  MilestoneState,
  ReferralOverview,
} from "../types";
import { AppleEmojiSticker } from "./AppleEmojiSticker";
import { presentStatus } from "./friendStatus";
import { emojiForMilestone } from "./referralVisuals";
import { useUpdateLink } from "./useUpdateLink";

// The production referral hub. Same hierarchy + polish as the /dev/referrals
// GAIA Native exploration, wired to live data and mutations. One page,
// intentional hierarchy: the journey toward free months is the hero; the share
// block is the one surface that earns a card; everything secondary flows as
// quiet lists. Inter only, sentence-case labels, GAIA tokens, cyan sparingly.

const EASE = [0.19, 1, 0.22, 1] as const;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SHARE_MESSAGE =
  "I've been using GAIA, a proactive personal AI assistant. Here's 50% off your first 2 months of Pro:";

const HOW_IT_WORKS: { title: string; body: string }[] = [
  {
    title: "Share your invite link",
    body: "Send it to friends over WhatsApp, X, email, or anywhere else.",
  },
  {
    title: "Your friend gets 50% off Pro and subscribes",
    body: "They save 50% on their first 2 months, a $30 gift.",
  },
  {
    title: "You earn a free month of Pro",
    body: "Keep inviting to stack months and climb the reward ladder.",
  },
];

// A staggered fade-up used for each band on mount.
const reveal = (delay: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: EASE, delay },
});

// ── Ladder geometry ────────────────────────────────────────────────────────
// Horizontal center (0..100) of milestone column `index` when the ladder is
// drawn as N evenly-spaced columns, so the node dot, sticker, and labels share
// one axis and a column reads as a single plumb vertical stack.
const columnCenterPct = (index: number, count: number): number =>
  ((index + 0.5) / count) * 100;

// Map the current points onto the even-column axis by interpolating between the
// two surrounding milestone thresholds, so "you are here" lands proportionally
// between the relevant stickers (not on a raw linear point scale).
function pointsToLadderPct(points: number, ladder: MilestoneState[]): number {
  const count = ladder.length;
  if (count === 0) return 0;
  const firstCenter = columnCenterPct(0, count);
  const lastCenter = columnCenterPct(count - 1, count);

  if (points <= ladder[0].threshold) {
    const frac = ladder[0].threshold > 0 ? points / ladder[0].threshold : 0;
    return Math.max(0, frac) * firstCenter;
  }
  if (points >= ladder[count - 1].threshold) return lastCenter;

  for (let i = 0; i < count - 1; i++) {
    const lo = ladder[i];
    const hi = ladder[i + 1];
    if (points >= lo.threshold && points <= hi.threshold) {
      const span = hi.threshold - lo.threshold;
      const frac = span > 0 ? (points - lo.threshold) / span : 0;
      return (
        columnCenterPct(i, count) +
        frac * (columnCenterPct(i + 1, count) - columnCenterPct(i, count))
      );
    }
  }
  return lastCenter;
}

function relativeTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "";
  }
}

// ── Hub ──────────────────────────────────────────────────────────────────────
function ReferralsHub({ overview }: { overview: ReferralOverview }) {
  const { code, share_link, points, next_goal_threshold, ladder, stats } =
    overview;
  const nextMilestone = ladder.find((tier) => tier.status === "next");
  const pointsToNext = nextMilestone
    ? Math.max(0, nextMilestone.threshold - points)
    : 0;
  const youPct = pointsToLadderPct(points, ladder);
  const fill = youPct;

  const [copied, setCopied] = useState(false);
  const invite = useInviteFriends();
  const link = useUpdateLink(code);
  const [email, setEmail] = useState("");

  const copyText = async (text: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(successMessage);
    } catch {
      toast.error("Couldn't copy. Select the text manually.");
    }
  };

  const copyLink = async () => {
    await copyText(share_link, "Invite link copied");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const openShare = (url: string) => window.open(url, "_blank", "noopener");

  const whatsAppUrl = `https://wa.me/?text=${encodeURIComponent(`${SHARE_MESSAGE} ${share_link}`)}`;
  const xUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(SHARE_MESSAGE)}&url=${encodeURIComponent(share_link)}`;
  const mailUrl = `mailto:?subject=${encodeURIComponent("Try GAIA with me")}&body=${encodeURIComponent(`${SHARE_MESSAGE}\n\n${share_link}`)}`;

  const sendInvite = () => {
    const valid = email
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter at least one valid email address");
      return;
    }
    invite.mutate(valid, { onSuccess: () => setEmail("") });
  };

  const onEmailKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendInvite();
    }
  };

  // The displayed link is "<prefix><slug>"; only the vanity slug is editable.
  const displayLink = share_link.replace(/^https?:\/\//, "");
  const prefix = displayLink.slice(0, displayLink.lastIndexOf("/") + 1);

  return (
    <SettingsPage>
      <div className="flex flex-col">
        {/* Offer intro: the gift icon folded inline with a quiet label. */}
        <m.div {...reveal(0)} className="flex flex-col items-start">
          <div className="inline-flex items-center gap-2 rounded-full bg-primary/15 py-1 pl-1 pr-3">
            <span className="flex size-6 items-center justify-center rounded-full bg-primary/20">
              <GiftIcon size={14} className="text-primary" />
            </span>
            <span className="text-xs font-medium text-primary">
              Refer a friend
            </span>
          </div>
          <h1 className="mt-5 text-balance text-3xl font-semibold leading-[1.1] tracking-tight text-white">
            Give a friend GAIA Pro.
            <br />
            Get a month free.
          </h1>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-zinc-400">
            They get 50% off their first 2 months. A $30 gift. You earn a free
            month of Pro when they subscribe.
          </p>
        </m.div>

        {/* Progress and reward ladder, the hero of the page. */}
        <m.div {...reveal(0.06)} className="mt-12">
          <p className="text-sm text-zinc-400">Toward your next reward</p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-6xl font-semibold tabular-nums tracking-tight text-white">
              {points}
            </span>
            <span className="text-xl font-medium text-zinc-500">
              {nextMilestone ? `/ ${next_goal_threshold} points` : "points"}
            </span>
          </div>
          <p className="mt-2 text-sm text-zinc-400">
            {nextMilestone ? (
              <>
                <span className="font-medium text-primary">
                  {pointsToNext} points left
                </span>{" "}
                until {nextMilestone.cumulative_months} months free
              </>
            ) : (
              "You've unlocked every reward."
            )}
          </p>

          <RewardLadder ladder={ladder} fill={fill} youPct={youPct} />
        </m.div>

        {/* Share block: the one card that earns it. Three tiers: invite link
            (primary), social channels (secondary, icon-only), email invite. */}
        <m.div {...reveal(0.12)} className="mt-12 rounded-2xl bg-zinc-800 p-5">
          {/* Tier 1: invite link, the hero of the card */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-zinc-500">Your invite link</p>
            {!link.editing && (
              <button
                type="button"
                onClick={link.start}
                className="inline-flex items-center gap-1 text-xs text-zinc-500 transition-colors hover:text-zinc-300"
              >
                <PencilEdit01Icon size={13} aria-hidden />
                Edit
              </button>
            )}
          </div>

          {link.editing ? (
            // Inline edit state: fixed prefix + editable slug, then Save/Cancel.
            // Save calls the real PATCH /referrals/code via useUpdateReferralCode.
            <div className="mt-2 flex flex-wrap items-center gap-2.5">
              <div className="flex h-11 min-w-0 flex-1 items-center rounded-xl bg-zinc-900 pl-3.5 pr-1.5 ring-1 ring-inset ring-white/5">
                <span className="shrink-0 text-sm text-zinc-500">{prefix}</span>
                <Input
                  autoFocus
                  aria-label="Invite link slug"
                  value={link.draft}
                  onValueChange={link.setDraft}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") link.save();
                    if (e.key === "Escape") link.cancel();
                  }}
                  variant="flat"
                  classNames={{
                    inputWrapper:
                      "h-8 min-h-8 rounded-lg bg-transparent px-1.5 shadow-none data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent",
                    input: "text-sm text-zinc-100",
                  }}
                />
              </div>
              <div className="flex items-center gap-2">
                <Button
                  color="primary"
                  size="sm"
                  isLoading={link.saving}
                  onPress={link.save}
                  className="h-9 font-medium"
                >
                  Save
                </Button>
                <Button
                  variant="light"
                  size="sm"
                  onPress={link.cancel}
                  className="h-9 font-medium text-zinc-400 data-[hover=true]:text-zinc-200"
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="mt-2 flex items-center gap-2.5">
              <div className="flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-xl bg-zinc-900 px-3.5 ring-1 ring-inset ring-white/5">
                <Link01Icon
                  size={16}
                  className="shrink-0 text-zinc-500"
                  aria-hidden
                />
                <span className="truncate text-sm text-zinc-200">
                  {displayLink}
                </span>
              </div>
              <Button
                color="primary"
                size="sm"
                onPress={copyLink}
                className="h-9 shrink-0 font-medium"
                startContent={
                  copied ? (
                    <CheckmarkCircle02Icon size={15} />
                  ) : (
                    <CopyIcon size={15} />
                  )
                }
              >
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          )}

          {/* Tier 2: social channels, lighter and icon-only, brand-tinted */}
          <div className="mt-4 flex items-center gap-2.5">
            <span className="text-xs text-zinc-500">Share via</span>
            <div className="flex items-center gap-1.5">
              <ChannelIconButton
                label="WhatsApp"
                icon={<WhatsappIcon size={17} />}
                color="#25D366"
                onPress={() => openShare(whatsAppUrl)}
              />
              <ChannelIconButton
                label="Twitter"
                icon={<TwitterIcon size={17} />}
                color="#1DA1F2"
                onPress={() => openShare(xUrl)}
              />
              <ChannelIconButton
                label="Email"
                icon={<Mail01Icon size={17} />}
                onPress={() => openShare(mailUrl)}
              />
            </div>
          </div>

          <Divider className="my-4 bg-zinc-700/60" />

          {/* Tier 3: email invite, a distinct action */}
          <div className="mb-2 flex items-center gap-1.5">
            <MailAdd01Icon size={15} className="text-zinc-500" aria-hidden />
            <p className="text-xs text-zinc-500">Or invite by email</p>
          </div>
          <div className="flex items-center gap-2.5">
            <Input
              value={email}
              onValueChange={setEmail}
              onKeyDown={onEmailKey}
              placeholder="friend@email.com"
              variant="flat"
              classNames={{
                inputWrapper:
                  "h-11 rounded-xl bg-zinc-900 ring-1 ring-inset ring-white/5 data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
                input: "text-sm text-zinc-100 placeholder:text-zinc-500",
              }}
            />
            <Button
              onPress={sendInvite}
              variant="flat"
              size="sm"
              isLoading={invite.isPending}
              className="h-9 shrink-0 bg-zinc-700 font-medium text-zinc-100 data-[hover=true]:bg-zinc-600"
              startContent={
                !invite.isPending ? <SentIcon size={15} /> : undefined
              }
            >
              Send
            </Button>
          </div>
        </m.div>

        {/* Stats: inline figures, not boxes. */}
        <m.div
          {...reveal(0.16)}
          className="mt-12 flex items-center justify-between"
        >
          <Stat label="Invited" value={stats.invited} />
          <StatDivider />
          <Stat label="Joined" value={stats.joined} />
          <StatDivider />
          <Stat label="Upgraded" value={stats.upgraded} />
          <StatDivider />
          <Stat label="Months earned" value={stats.months_earned} accent />
        </m.div>

        {/* How it works, a numbered stepper. */}
        <m.section {...reveal(0.2)} className="mt-12">
          <h2 className="mb-4 text-sm font-medium text-zinc-300">
            How it works
          </h2>
          <ol className="flex flex-col">
            {HOW_IT_WORKS.map((item, i) => {
              const last = i === HOW_IT_WORKS.length - 1;
              return (
                <li key={item.title} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold tabular-nums text-zinc-200">
                      {i + 1}
                    </span>
                    {!last && <span className="my-1 w-px flex-1 bg-zinc-800" />}
                  </div>
                  <div className={cn("pt-0.5", last ? "pb-0" : "pb-6")}>
                    <p className="text-sm font-medium text-zinc-200">
                      {item.title}
                    </p>
                    <p className="mt-1 text-sm leading-relaxed text-zinc-500">
                      {item.body}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </m.section>

        {/* Friends and rewards, two full-width cards stacked vertically. */}
        <m.div {...reveal(0.24)} className="mt-12 flex flex-col gap-4">
          <FriendsCard friends={overview.friends} />
          <RewardsCard
            rewards={overview.rewards}
            firstThreshold={ladder[0]?.threshold ?? 100}
            onCopyCode={(c) => copyText(c, "Code copied")}
          />
        </m.div>
      </div>
    </SettingsPage>
  );
}

// ── Reward ladder ────────────────────────────────────────────────────────────
// N evenly-spaced columns. Rail, fill, node dots, and the you-are-here knob
// live in one bar whose node dots sit at the column centers, so each column
// reads as a single plumb vertical stack.
function RewardLadder({
  ladder,
  fill,
  youPct,
}: {
  ladder: MilestoneState[];
  fill: number;
  youPct: number;
}) {
  const count = ladder.length;
  if (count === 0) return null;

  return (
    <div className="mt-9">
      <div className="relative h-2 w-full rounded-full bg-zinc-800">
        <m.div
          initial={{ width: 0 }}
          animate={{ width: `${fill}%` }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
          className="absolute inset-y-0 left-0 rounded-full bg-primary"
        />
        {ladder.map((tier, i) => (
          <span
            key={tier.threshold}
            className={cn(
              "absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
              tier.status === "done" ? "bg-primary" : "bg-zinc-600",
            )}
            style={{ left: `${columnCenterPct(i, count)}%` }}
          />
        ))}
        <m.span
          initial={{ opacity: 0, scale: 0 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: EASE, delay: 1.0 }}
          className="absolute top-1/2 z-10 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-zinc-800 bg-primary"
          style={{ left: `${youPct}%` }}
        />
      </div>

      <div className="mt-3 flex">
        {ladder.map((tier, i) => {
          const done = tier.status === "done";
          const isNext = tier.status === "next";
          return (
            <div
              key={tier.threshold}
              className="flex flex-1 flex-col items-center gap-1.5 text-center"
            >
              <AppleEmojiSticker
                emoji={emojiForMilestone(i)}
                size={34}
                dimmed={!done}
                pulse={isNext}
              />
              <span
                className={cn(
                  "text-xs font-medium leading-tight",
                  done
                    ? "text-zinc-200"
                    : isNext
                      ? "text-primary"
                      : "text-zinc-500",
                )}
              >
                {tier.cumulative_months}{" "}
                {tier.cumulative_months === 1 ? "mo" : "mos"} free
              </span>
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                  done
                    ? "bg-primary/15 text-primary"
                    : "bg-zinc-800 text-zinc-500",
                )}
              >
                +{tier.reward_months} at {tier.threshold}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Friends card ─────────────────────────────────────────────────────────────
function FriendsCard({ friends }: { friends: FriendReferral[] }) {
  return (
    <section className="rounded-3xl bg-zinc-900/60 p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-300">
          Friends you&apos;ve invited
        </h2>
        {friends.length > 0 && (
          <span className="text-xs text-zinc-500">{friends.length} total</span>
        )}
      </div>
      {friends.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-500">
          No friends yet. Share your link to get started.
        </p>
      ) : (
        <div className="divide-y divide-zinc-800/70">
          {friends.map((friend) => {
            const status = presentStatus(friend.status);
            const when = relativeTime(friend.upgraded_at ?? friend.created_at);
            return (
              <div
                key={`${friend.display}-${friend.created_at}`}
                className="flex items-center gap-3 py-2.5"
              >
                <Avatar name={friend.display} size="sm" className="shrink-0" />
                <p className="min-w-0 flex-1 truncate text-sm text-zinc-200">
                  {friend.display}
                </p>
                {when && (
                  <span className="hidden shrink-0 text-xs text-zinc-600 sm:block">
                    {when}
                  </span>
                )}
                <Chip
                  color={status.chipColor}
                  variant="flat"
                  size="sm"
                  className="shrink-0 text-xs"
                >
                  {status.label}
                </Chip>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Rewards card ─────────────────────────────────────────────────────────────
function RewardsCard({
  rewards,
  firstThreshold,
  onCopyCode,
}: {
  rewards: EarnedReward[];
  firstThreshold: number;
  onCopyCode: (code: string) => void;
}) {
  const granted = rewards.filter((r) => r.status === "granted");
  return (
    <section className="rounded-3xl bg-zinc-900/60 p-4">
      <h2 className="mb-2 text-sm font-medium text-zinc-300">Rewards earned</h2>
      {granted.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-500">
          No rewards yet. Your first free month unlocks at {firstThreshold}{" "}
          points.
        </p>
      ) : (
        <div className="divide-y divide-zinc-800/70">
          {granted.map((reward) => {
            const label =
              reward.months_granted === 1
                ? "1 month of Pro, free"
                : `${reward.months_granted} months of Pro, free`;
            return (
              <div
                key={`${reward.milestone_threshold}-${reward.granted_at}`}
                className="flex flex-wrap items-center gap-3 py-2.5"
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15">
                  <GiftIcon size={17} className="text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-zinc-200">{label}</p>
                  <p className="text-xs text-zinc-500">
                    {reward.discount_code
                      ? "Apply this code at checkout or in Billing."
                      : "Applied to your subscription."}
                  </p>
                </div>
                {reward.discount_code ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="flat"
                    disableRipple
                    aria-label={`Copy code ${reward.discount_code}`}
                    onPress={() => onCopyCode(reward.discount_code ?? "")}
                    className="group h-auto min-w-0 gap-1.5 rounded-lg bg-zinc-800 px-2.5 py-1.5 font-mono text-xs text-zinc-200 data-[hover=true]:bg-zinc-700"
                    endContent={
                      <CopyIcon
                        size={13}
                        className="text-zinc-500 transition-colors group-data-[hover=true]:text-zinc-300"
                      />
                    }
                  >
                    {reward.discount_code}
                  </Button>
                ) : (
                  <Chip
                    color="success"
                    variant="flat"
                    size="sm"
                    className="text-xs"
                    startContent={<CheckmarkCircle02Icon size={13} />}
                  >
                    Applied
                  </Chip>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Small pieces ─────────────────────────────────────────────────────────────
function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div className="flex flex-col">
      <span
        className={cn(
          "text-2xl font-semibold tabular-nums tracking-tight",
          accent ? "text-primary" : "text-white",
        )}
      >
        {value}
      </span>
      <span className="mt-0.5 text-xs text-zinc-500">{label}</span>
    </div>
  );
}

function StatDivider() {
  return <span className="mx-3 h-8 w-px shrink-0 bg-zinc-800" />;
}

function ChannelIconButton({
  icon,
  label,
  onPress,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  onPress: () => void;
  /** Brand hex for the icon tint + a subtle tinted hover background. Omit for a
   *  neutral zinc treatment. */
  color?: string;
}) {
  return (
    <Tooltip content={label} delay={200} closeDelay={0} size="sm">
      <Button
        isIconOnly
        radius="full"
        variant="light"
        size="sm"
        aria-label={label}
        onPress={onPress}
        style={
          color
            ? ({ color, "--brand-bg": `${color}24` } as React.CSSProperties)
            : undefined
        }
        className={cn(
          "size-9",
          color
            ? "data-[hover=true]:bg-[var(--brand-bg)]"
            : "text-zinc-400 data-[hover=true]:bg-zinc-700/60 data-[hover=true]:text-zinc-100",
        )}
      >
        {icon}
      </Button>
    </Tooltip>
  );
}

// ── Loading + entry ──────────────────────────────────────────────────────────
function ReferralsSkeleton() {
  return (
    <SettingsPage>
      <div className="flex flex-col">
        <Skeleton className="h-6 w-32 rounded-full" />
        <Skeleton className="mt-5 h-16 w-80 rounded-xl" />
        <Skeleton className="mt-12 h-20 w-full rounded-2xl" />
        <Skeleton className="mt-9 h-24 w-full rounded-2xl" />
        <Skeleton className="mt-12 h-40 w-full rounded-2xl" />
        <div className="mt-12 flex gap-3">
          {["a", "b", "c", "d"].map((k) => (
            <Skeleton key={k} className="h-12 flex-1 rounded-xl" />
          ))}
        </div>
        <Skeleton className="mt-12 h-44 w-full rounded-3xl" />
      </div>
    </SettingsPage>
  );
}

export function ReferralsSettings() {
  const { data: overview, isLoading } = useReferralOverview();

  return (
    <LazyMotionProvider>
      {isLoading || !overview ? (
        <ReferralsSkeleton />
      ) : (
        <ReferralsHub overview={overview} />
      )}
    </LazyMotionProvider>
  );
}
