"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Progress } from "@heroui/progress";
import { Tooltip } from "@heroui/tooltip";
import {
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  GiftIcon,
} from "@icons";
import * as m from "motion/react-m";
import { useState } from "react";
import { TextMorph } from "torph/react";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

// Standalone mock so the gallery renders without the referral data hook.
const MOCK = {
  share_link: "gaia.app/r/aryan",
  code: "aryan",
  points: 200,
  progress_pct: 66,
  friends_joined: 3,
  next_goal_reward_months: 1,
};

const HEADLINE = "Invite friends, get a free month of Pro";
const EASE = [0.16, 1, 0.3, 1] as const;

/** Gift glyph in a full filled primary circle — shared across variants. */
function GiftCircle({
  size = 24,
  icon = 14,
}: {
  size?: number;
  icon?: number;
}) {
  return (
    <span
      className="flex items-center justify-center rounded-full bg-primary text-black"
      style={{ width: size, height: size }}
    >
      <GiftIcon width={icon} height={icon} />
    </span>
  );
}

/** Mock copy-link control with copied feedback. */
function CopyLink({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(MOCK.share_link);
    } catch {
      // clipboard unavailable in some contexts — still flash the confirmation
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className={`flex items-center gap-2 rounded-xl bg-zinc-900/70 px-3 py-2 text-left transition-colors hover:bg-zinc-900 ${className}`}
    >
      <span className="flex-1 truncate font-mono text-xs text-zinc-300">
        {MOCK.share_link}
      </span>
      {copied ? (
        <CheckmarkCircle02Icon
          width={16}
          height={16}
          className="text-primary"
        />
      ) : (
        <Copy01Icon width={16} height={16} className="text-zinc-400" />
      )}
    </button>
  );
}

/** Shared popover body that holds the share affordance + value line. */
function SharePopoverBody() {
  return (
    <div className="w-[280px] space-y-3">
      <div>
        <p className="text-sm font-medium text-zinc-100">
          One free month of Pro away
        </p>
        <p className="text-xs text-zinc-500">
          Every friend who subscribes earns you a free month.
        </p>
      </div>
      <CopyLink className="w-full" />
    </div>
  );
}

// ── Variant 1: Labeled mini-card (production baseline) ──────────────────────
function LabeledMiniCard() {
  return (
    <Popover placement="top-end" offset={12} radius="lg">
      <m.div
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.4, ease: EASE }}
        className="w-[264px] overflow-hidden rounded-2xl bg-zinc-800/40 p-3 backdrop-blur-xl"
      >
        <div className="mb-2 flex items-center gap-2">
          <GiftCircle />
          <span className="text-sm font-medium text-zinc-100">{HEADLINE}</span>
        </div>
        <Progress
          aria-label="Referral progress"
          size="sm"
          color="primary"
          value={MOCK.progress_pct}
          className="mb-2"
        />
        <PopoverTrigger>
          <Button
            size="sm"
            color="primary"
            className="w-full rounded-xl text-xs font-medium text-black"
          >
            Share &amp; earn
          </Button>
        </PopoverTrigger>
      </m.div>
      <PopoverContent className="rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
        <SharePopoverBody />
      </PopoverContent>
    </Popover>
  );
}

// ── Variant 2: Compact pill (morphs into a card on hover) ───────────────────
function CompactPill() {
  const [open, setOpen] = useState(false);
  const r = 9;
  const c = 2 * Math.PI * r;
  // The box morphs HEIGHT + corner only — the width is fixed, so the text is
  // never width-animated or stretched. The text content itself morphs at the
  // character level with torph, and the gift icon is a fixed-size circle, so
  // nothing ever scales/distorts.
  return (
    <m.div
      onHoverStart={() => setOpen(true)}
      onHoverEnd={() => setOpen(false)}
      initial={{ opacity: 0, y: 12, height: 48, borderRadius: 24 }}
      animate={{
        opacity: 1,
        y: 0,
        height: open ? 134 : 48,
        borderRadius: open ? 20 : 24,
      }}
      transition={{
        opacity: { duration: 0.4, ease: EASE },
        y: { duration: 0.4, ease: EASE },
        height: { duration: 0.42, ease: EASE },
        borderRadius: { duration: 0.42, ease: EASE },
      }}
      className="flex w-[256px] cursor-pointer flex-col overflow-hidden bg-zinc-800/40 p-2 backdrop-blur-xl"
    >
      <div className="flex h-8 shrink-0 items-center gap-2.5 px-1">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
          <GiftIcon width={15} height={15} />
        </span>
        <TextMorph
          duration={420}
          ease="cubic-bezier(0.19, 1, 0.22, 1)"
          className="text-sm font-medium text-zinc-100"
        >
          {open ? "Get a free month of Pro" : "Invite & earn"}
        </TextMorph>
        {!open && (
          <span className="relative ml-auto flex size-6 shrink-0 items-center justify-center">
            <svg
              width={24}
              height={24}
              className="-rotate-90"
              aria-hidden="true"
            >
              <circle
                cx={12}
                cy={12}
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth={2.5}
                className="text-zinc-700"
              />
              <circle
                cx={12}
                cy={12}
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeDasharray={c}
                strokeDashoffset={c * (1 - MOCK.progress_pct / 100)}
                className="text-primary"
              />
            </svg>
          </span>
        )}
      </div>
      <div className="mt-1 px-1">
        <p className="mb-2.5 px-1 text-xs leading-relaxed text-zinc-400">
          They get 50% off 2 months. You earn a free month when they subscribe.
        </p>
        <Popover placement="top-end" offset={12} radius="lg">
          <PopoverTrigger>
            <Button
              size="sm"
              color="primary"
              className="w-full rounded-xl text-sm font-medium text-black"
            >
              Share &amp; earn
            </Button>
          </PopoverTrigger>
          <PopoverContent className="rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
            <SharePopoverBody />
          </PopoverContent>
        </Popover>
      </div>
    </m.div>
  );
}

// ── Variant 3: Progress-ring FAB ────────────────────────────────────────────
function ProgressRingFab() {
  const r = 26;
  const c = 2 * Math.PI * r;
  return (
    <Popover placement="top-end" offset={12} radius="lg">
      <Tooltip
        content="Invite friends, get a free month"
        placement="left"
        radius="lg"
        classNames={{ content: "bg-zinc-900 text-xs text-zinc-200" }}
      >
        <PopoverTrigger>
          <m.button
            type="button"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, ease: EASE }}
            aria-label="Invite friends, get a free month"
            className="relative flex size-16 items-center justify-center rounded-full bg-zinc-800/40 backdrop-blur-xl transition-colors hover:bg-zinc-800/60"
          >
            <svg
              width={64}
              height={64}
              className="-rotate-90 absolute inset-0"
              aria-hidden="true"
            >
              <circle
                cx={32}
                cy={32}
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth={3}
                className="text-zinc-700"
              />
              <circle
                cx={32}
                cy={32}
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray={c}
                strokeDashoffset={c * (1 - MOCK.progress_pct / 100)}
                className="text-primary"
              />
            </svg>
            <GiftCircle size={36} icon={18} />
          </m.button>
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent className="rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
        <SharePopoverBody />
      </PopoverContent>
    </Popover>
  );
}

// ── Variant 4: Avatar-stack card ────────────────────────────────────────────
const AVATARS = ["#3f3f46", "#52525b", "#71717a"];
function AvatarStackCard() {
  return (
    <Popover placement="top-end" offset={12} radius="lg">
      <m.div
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.4, ease: EASE }}
        className="w-[272px] rounded-2xl bg-zinc-800/40 p-3.5 backdrop-blur-xl"
      >
        <div className="mb-3 flex items-center gap-3">
          <div className="flex items-center -space-x-2">
            {AVATARS.map((bg, i) => (
              <span
                key={bg}
                className="flex size-7 items-center justify-center rounded-full ring-2 ring-zinc-900 text-[11px] font-semibold text-zinc-300"
                style={{ backgroundColor: bg, zIndex: AVATARS.length - i }}
              >
                {String.fromCharCode(65 + i)}
              </span>
            ))}
            <span className="z-0 flex size-7 items-center justify-center rounded-full bg-primary text-black ring-2 ring-zinc-900">
              <GiftIcon width={13} height={13} />
            </span>
          </div>
          <div className="leading-tight">
            <p className="text-sm font-medium text-zinc-100">
              {MOCK.friends_joined} friends joined
            </p>
            <p className="text-xs text-zinc-500">
              Invite more, earn a free month
            </p>
          </div>
        </div>
        <PopoverTrigger>
          <Button
            size="sm"
            color="primary"
            className="w-full rounded-xl text-xs font-medium text-black"
            endContent={<ArrowRight01Icon width={14} height={14} />}
          >
            Invite friends
          </Button>
        </PopoverTrigger>
      </m.div>
      <PopoverContent className="rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
        <SharePopoverBody />
      </PopoverContent>
    </Popover>
  );
}

// ── Variant 5: Minimal text + CTA ───────────────────────────────────────────
function MinimalTextCta() {
  return (
    <Popover placement="top-end" offset={12} radius="lg">
      <m.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: EASE }}
        className="flex items-center gap-3 rounded-2xl bg-zinc-800/40 py-2 pr-2 pl-3.5 backdrop-blur-xl"
      >
        <GiftCircle size={22} icon={12} />
        <span className="text-sm text-zinc-200">
          Give a friend a month, get one free
        </span>
        <PopoverTrigger>
          <Button
            size="sm"
            color="primary"
            className="rounded-xl text-xs font-medium text-black"
          >
            Invite
          </Button>
        </PopoverTrigger>
      </m.div>
      <PopoverContent className="rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
        <SharePopoverBody />
      </PopoverContent>
    </Popover>
  );
}

const VARIANTS: { caption: string; Component: () => React.ReactElement }[] = [
  { caption: "1 · Labeled mini-card (baseline)", Component: LabeledMiniCard },
  { caption: "2 · Compact pill", Component: CompactPill },
  { caption: "3 · Progress-ring FAB", Component: ProgressRingFab },
  { caption: "4 · Avatar-stack card", Component: AvatarStackCard },
  { caption: "5 · Minimal text + CTA", Component: MinimalTextCta },
];

export default function CornerBarGallery() {
  return (
    <LazyMotionProvider>
      <div className="min-h-full bg-[#111111] px-6 py-10">
        <div className="mx-auto max-w-5xl">
          <header className="mb-8">
            <h1 className="text-lg font-semibold text-zinc-100">
              Corner referral bar — 5 variants
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Five takes on the bottom-right invite nudge. Each is positioned in
              a mock app corner. All controls are interactive (mock data).
            </p>
          </header>

          <div className="grid grid-cols-1 gap-x-6 gap-y-8 md:grid-cols-2">
            {VARIANTS.map(({ caption, Component }) => (
              <div key={caption}>
                <p className="mb-2 text-xs font-medium text-zinc-400">
                  {caption}
                </p>
                <div className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-zinc-900/40">
                  <div className="absolute right-4 bottom-4">
                    <Component />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </LazyMotionProvider>
  );
}
