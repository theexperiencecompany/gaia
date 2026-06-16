"use client";

import { Avatar } from "@heroui/avatar";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Input } from "@heroui/input";
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
import * as m from "motion/react-m";
import { useState } from "react";

import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { DevSticker } from "./DevSticker";
import {
  buildMailUrl,
  buildWhatsAppUrl,
  buildXUrl,
  columnCenterPct,
  EARNED_REWARDS,
  FRIEND_OFFER_VALUE,
  FRIEND_STATUS_LABEL,
  FRIENDS,
  type FriendStatus,
  HOW_IT_WORKS,
  INVITE_PATH,
  isUnlocked,
  ladderFillPct,
  MILESTONES,
  nextMilestone,
  POINTS_EARNED,
  pointsToLadderPct,
  STATS,
} from "./mockData";
import { useEmailInvite } from "./useEmailInvite";

// GAIA NATIVE, the production-candidate referral page.
//
// One page, intentional hierarchy. The journey toward free months is the hero:
// a single progression track with milestone nodes aligned to their real point
// thresholds, so "you are here" connects visually to the next reward. The
// share block is the one surface that earns a card; everything secondary flows
// as quiet lists separated by whitespace and hairlines. Inter only,
// sentence-case labels, GAIA tokens, cyan used sparingly.

const EASE = [0.19, 1, 0.22, 1] as const;

const STATUS_CHIP: Record<FriendStatus, "primary" | "warning" | "default"> = {
  upgraded: "primary",
  joined: "warning",
  invited: "default",
};

// A staggered fade-up used on mount.
const reveal = (delay: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: EASE, delay },
});

// The invite link is "<prefix><slug>". The prefix is fixed; only the vanity
// slug is editable.
const INVITE_PREFIX = INVITE_PATH.slice(0, INVITE_PATH.lastIndexOf("/") + 1);
const INITIAL_SLUG = INVITE_PATH.slice(INVITE_PATH.lastIndexOf("/") + 1);
// Lowercase letters/numbers, single hyphens between (no leading/trailing or
// doubled hyphens), length 3 to 32.
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function GaiaNative() {
  const [copied, setCopied] = useState(false);
  const [slug, setSlug] = useState(INITIAL_SLUG);
  const [editingLink, setEditingLink] = useState(false);
  const [slugDraft, setSlugDraft] = useState(INITIAL_SLUG);
  const invite = useEmailInvite((count, emails) =>
    count === 1
      ? `Invite sent to ${emails[0]}`
      : `Invite sent to ${count} friends`,
  );
  const next = nextMilestone();
  const fill = ladderFillPct();
  const youPct = pointsToLadderPct(POINTS_EARNED);
  const pointsToNext = next ? next.points - POINTS_EARNED : 0;

  // Live link reflects the locally edited slug. The link field, Copy, and the
  // channel-share helpers all read this so they stay in sync after an edit.
  const invitePath = `${INVITE_PREFIX}${slug}`;
  const inviteUrl = `https://${invitePath}`;

  // Shared clipboard helper, reused by both the link Copy and the reward code.
  const copyText = async (text: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(successMessage);
    } catch {
      toast.error("Couldn't copy. Select the text manually.");
    }
  };

  const copy = async () => {
    await copyText(inviteUrl, "Invite link copied");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const startEditLink = () => {
    setSlugDraft(slug);
    setEditingLink(true);
  };

  const cancelEditLink = () => {
    setEditingLink(false);
    setSlugDraft(slug);
  };

  // In production this maps to the backend PATCH /referrals/code
  // (useUpdateReferralCode); here it only updates local demo state.
  const saveLink = () => {
    const nextSlug = slugDraft.trim().toLowerCase();
    if (nextSlug.length < 3 || nextSlug.length > 32) {
      toast.error("Use 3 to 32 characters.");
      return;
    }
    if (!SLUG_PATTERN.test(nextSlug)) {
      toast.error("Use lowercase letters, numbers, and single hyphens.");
      return;
    }
    setSlug(nextSlug);
    setEditingLink(false);
    toast.success("Invite link updated");
  };

  return (
    <div className="min-h-full bg-[#111111] px-5 py-12 sm:px-6 sm:py-16">
      <div className="mx-auto flex max-w-xl flex-col">
        {/*  Offer intro gift icon folded inline with a quiet label  */}
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
            They get 50% off their first 2 months. A {FRIEND_OFFER_VALUE} gift.
            You earn a free month of Pro when they subscribe.
          </p>
        </m.div>

        {/* Progress and reward ladder, the hero of the page. */}
        <m.div {...reveal(0.06)} className="mt-12">
          <p className="text-sm text-zinc-400">Toward your next reward</p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-6xl font-semibold tabular-nums tracking-tight text-white">
              {POINTS_EARNED}
            </span>
            <span className="text-xl font-medium text-zinc-500">
              {next ? `/ ${next.points} points` : "points"}
            </span>
          </div>
          <p className="mt-2 text-sm text-zinc-400">
            {next ? (
              <>
                <span className="font-medium text-primary">
                  {pointsToNext} points left
                </span>{" "}
                until {next.monthsTotal} months free
              </>
            ) : (
              "You've unlocked every reward."
            )}
          </p>

          <RewardLadder fill={fill} youPct={youPct} nextId={next?.id} />
        </m.div>

        {/* Share block: the one card that earns it. Three tiers, clearly
            distinct: the invite link (primary), social channels (secondary,
            icon-only), and email invite (its own action below a divider). */}
        <m.div {...reveal(0.12)} className="mt-12 rounded-2xl bg-zinc-800 p-5">
          {/* Tier 1: invite link, the hero of the card */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-zinc-500">Your invite link</p>
            {!editingLink && (
              <button
                type="button"
                onClick={startEditLink}
                className="inline-flex items-center gap-1 text-xs text-zinc-500 transition-colors hover:text-zinc-300"
              >
                <PencilEdit01Icon size={13} aria-hidden />
                Edit
              </button>
            )}
          </div>

          {editingLink ? (
            // Inline edit state: fixed prefix + editable slug, then Save/Cancel.
            <div className="mt-2 flex flex-wrap items-center gap-2.5">
              <div className="flex h-11 min-w-0 flex-1 items-center rounded-xl bg-zinc-900 pl-3.5 pr-1.5 ring-1 ring-inset ring-white/5">
                <span className="shrink-0 text-sm text-zinc-500">
                  {INVITE_PREFIX}
                </span>
                <Input
                  autoFocus
                  aria-label="Invite link slug"
                  value={slugDraft}
                  onValueChange={setSlugDraft}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveLink();
                    if (e.key === "Escape") cancelEditLink();
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
                  onPress={saveLink}
                  className="h-9 font-medium"
                >
                  Save
                </Button>
                <Button
                  variant="light"
                  size="sm"
                  onPress={cancelEditLink}
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
                  {invitePath}
                </span>
              </div>
              <Button
                color="primary"
                size="sm"
                onPress={copy}
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
                onPress={() =>
                  window.open(buildWhatsAppUrl(inviteUrl), "_blank", "noopener")
                }
              />
              <ChannelIconButton
                label="Twitter"
                icon={<TwitterIcon size={17} />}
                color="#1DA1F2"
                onPress={() =>
                  window.open(buildXUrl(inviteUrl), "_blank", "noopener")
                }
              />
              <ChannelIconButton
                label="Email"
                icon={<Mail01Icon size={17} />}
                onPress={() =>
                  window.open(buildMailUrl(inviteUrl), "_blank", "noopener")
                }
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
              value={invite.email}
              onValueChange={invite.setEmail}
              onKeyDown={invite.onKeyDown}
              placeholder="friend@email.com"
              variant="flat"
              classNames={{
                inputWrapper:
                  "h-11 rounded-xl bg-zinc-900 ring-1 ring-inset ring-white/5 data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
                input: "text-sm text-zinc-100 placeholder:text-zinc-500",
              }}
            />
            <Button
              onPress={invite.send}
              variant="flat"
              size="sm"
              className="h-9 shrink-0 bg-zinc-700 font-medium text-zinc-100 data-[hover=true]:bg-zinc-600"
              startContent={<SentIcon size={15} />}
            >
              Send
            </Button>
          </div>
        </m.div>

        {/*  Stats inline figures, not boxes  */}
        <m.div
          {...reveal(0.16)}
          className="mt-12 flex items-center justify-between"
        >
          <Stat label="Invited" value={STATS.invited} />
          <StatDivider />
          <Stat label="Joined" value={STATS.joined} />
          <StatDivider />
          <Stat label="Upgraded" value={STATS.upgraded} />
          <StatDivider />
          <Stat label="Months earned" value={STATS.monthsEarned} accent />
        </m.div>

        {/* How it works, right under the share area as a numbered stepper */}
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

        {/* Friends and rewards, two full-width cards stacked vertically */}
        <m.div {...reveal(0.24)} className="mt-12 flex flex-col gap-4">
          {/* Friends card */}
          <section className="rounded-3xl bg-zinc-900/60 p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-sm font-medium text-zinc-300">
                Friends you&apos;ve invited
              </h2>
              <span className="text-xs text-zinc-500">
                {FRIENDS.length} total
              </span>
            </div>
            <div className="divide-y divide-zinc-800/70">
              {FRIENDS.map((friend) => (
                <div
                  key={friend.email}
                  className="flex items-center gap-3 py-2.5"
                >
                  <Avatar name={friend.name} size="sm" className="shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-zinc-200">
                      {friend.name}
                    </p>
                    <p className="truncate text-xs text-zinc-500">
                      {friend.email}
                    </p>
                  </div>
                  <span className="hidden shrink-0 text-xs text-zinc-600 sm:block">
                    {friend.when}
                  </span>
                  <Chip
                    color={STATUS_CHIP[friend.status]}
                    variant="flat"
                    size="sm"
                    className="shrink-0 text-xs"
                  >
                    {FRIEND_STATUS_LABEL[friend.status]}
                  </Chip>
                </div>
              ))}
            </div>
          </section>

          {/* Rewards card */}
          <section className="rounded-3xl bg-zinc-900/60 p-4">
            <h2 className="mb-2 text-sm font-medium text-zinc-300">
              Rewards earned
            </h2>
            <div className="divide-y divide-zinc-800/70">
              {EARNED_REWARDS.map((reward) => (
                <div
                  key={reward.id}
                  className="flex flex-wrap items-center gap-3 py-2.5"
                >
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15">
                    <GiftIcon size={17} className="text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-zinc-200">{reward.label}</p>
                    <p className="text-xs text-zinc-500">{reward.note}</p>
                  </div>
                  {reward.code ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="flat"
                      disableRipple
                      aria-label={`Copy code ${reward.code}`}
                      onPress={() => copyText(reward.code ?? "", "Code copied")}
                      className="group h-auto min-w-0 gap-1.5 rounded-lg bg-zinc-800 px-2.5 py-1.5 font-mono text-xs text-zinc-200 data-[hover=true]:bg-zinc-700"
                      endContent={
                        <CopyIcon
                          size={13}
                          className="text-zinc-500 transition-colors group-data-[hover=true]:text-zinc-300"
                        />
                      }
                    >
                      {reward.code}
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
              ))}
            </div>
          </section>
        </m.div>
      </div>
    </div>
  );
}

// Reward ladder drawn as N evenly-spaced columns. The rail, fill, knob, and
// node dots live in one absolutely-positioned bar whose node dots sit at the
// exact column centers, so each column reads as a single plumb vertical stack:
// node dot, sticker, "1 mo free", "+1 at 100". The fill maps the current points
// onto that same column axis, so "you are here" lines up between stickers.
function RewardLadder({
  fill,
  youPct,
  nextId,
}: {
  fill: number;
  youPct: number;
  nextId?: string;
}) {
  const count = MILESTONES.length;

  return (
    <div className="mt-9">
      {/* Rail + fill + node dots + you-are-here knob */}
      <div className="relative h-2 w-full rounded-full bg-zinc-800">
        <m.div
          initial={{ width: 0 }}
          animate={{ width: `${fill}%` }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
          className="absolute inset-y-0 left-0 rounded-full bg-primary"
        />
        {MILESTONES.map((milestone, i) => {
          const unlocked = isUnlocked(milestone);
          return (
            <span
              key={milestone.id}
              className={cn(
                "absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full",
                unlocked ? "bg-primary" : "bg-zinc-600",
              )}
              style={{ left: `${columnCenterPct(i, count)}%` }}
            />
          );
        })}
        <m.span
          initial={{ opacity: 0, scale: 0 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: EASE, delay: 1.0 }}
          className="absolute top-1/2 z-10 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#111111] bg-primary"
          style={{ left: `${youPct}%` }}
        />
      </div>

      {/* Even columns: each centered under its node dot */}
      <div className="mt-3 flex">
        {MILESTONES.map((milestone) => {
          const unlocked = isUnlocked(milestone);
          const isNext = nextId === milestone.id;
          return (
            <div
              key={milestone.id}
              className="flex flex-1 flex-col items-center gap-1.5 text-center"
            >
              <DevSticker
                emoji={milestone.emoji}
                size={34}
                dimmed={!unlocked}
                pulse={isNext}
              />
              <span
                className={cn(
                  "text-xs font-medium leading-tight",
                  unlocked
                    ? "text-zinc-200"
                    : isNext
                      ? "text-primary"
                      : "text-zinc-500",
                )}
              >
                {milestone.monthsTotal}{" "}
                {milestone.monthsTotal === 1 ? "mo" : "mos"} free
              </span>
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                  unlocked
                    ? "bg-primary/15 text-primary"
                    : "bg-zinc-800 text-zinc-500",
                )}
              >
                +{milestone.monthsAdded} at {milestone.points}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

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
  /** Brand hex for the icon tint + a subtle tinted hover background. Omit for
   *  a neutral zinc treatment. */
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
