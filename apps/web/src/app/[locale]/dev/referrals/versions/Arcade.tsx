"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  CheckmarkCircle02Icon,
  CopyIcon,
  LockIcon,
  Mail01Icon,
  NewTwitterIcon,
  RankingIcon,
  SentIcon,
  WhatsappIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, useMemo, useState } from "react";

import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { DevSticker } from "./DevSticker";
import {
  buildWhatsAppUrl,
  buildXUrl,
  EMAIL_PATTERN,
  INVITE_PATH,
  INVITE_URL,
  isUnlocked,
  LEADERBOARD,
  MILESTONES,
  nextMilestone,
  POINTS_EARNED,
} from "./mockData";
import { useCopyLink } from "./useCopyLink";

// ──────────────────────────────────────────────────────────────────────────
// Direction 3 — ARCADE
// Gamified quest. Condensed all-caps. Hero IS a milestone ROADMAP stepper of
// chunky tiles. Bold pill share card + big circular channel buttons. Chunky
// email input. Mini leaderboard. Loud color blocking, bouncy spring, CONFETTI
// + sticker peel-on. Duolingo / Blackbird / Wise.
// ──────────────────────────────────────────────────────────────────────────

const CONFETTI_COLORS = ["#00bbff", "#ffd166", "#ef476f", "#06d6a0", "#a78bfa"];
const SPRING = { type: "spring" as const, stiffness: 420, damping: 20 };

function ConfettiBurst({ show }: { show: boolean }) {
  const pieces = useMemo(
    () =>
      Array.from({ length: 28 }, (_, i) => ({
        id: i,
        x: (Math.random() - 0.5) * 320,
        y: -(60 + Math.random() * 220),
        rotate: Math.random() * 540,
        color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        delay: Math.random() * 0.08,
        size: 6 + Math.random() * 6,
      })),
    [],
  );

  return (
    <AnimatePresence>
      {show && (
        <div className="pointer-events-none absolute left-1/2 top-1/2 z-20">
          {pieces.map((p) => (
            <m.span
              key={p.id}
              initial={{ opacity: 1, x: 0, y: 0, rotate: 0 }}
              animate={{ opacity: 0, x: p.x, y: p.y, rotate: p.rotate }}
              transition={{
                duration: 0.9,
                delay: p.delay,
                ease: [0.16, 1, 0.3, 1],
              }}
              className="absolute rounded-[2px]"
              style={{
                width: p.size,
                height: p.size * 1.4,
                background: p.color,
              }}
            />
          ))}
        </div>
      )}
    </AnimatePresence>
  );
}

export function Arcade() {
  const { copied, copy } = useCopyLink(INVITE_URL);
  const [email, setEmail] = useState("");
  const [burst, setBurst] = useState(false);
  const next = nextMilestone();

  const handleCopy = () => {
    copy();
    setBurst(true);
    setTimeout(() => setBurst(false), 1000);
  };

  const sendInvite = () => {
    const valid = email
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter at least one valid email");
      return;
    }
    toast.success(`Boom — invited ${valid.length}!`);
    setEmail("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendInvite();
    }
  };

  return (
    <div className="min-h-full bg-[#0f1011] px-6 py-12 md:px-10">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="text-center">
          <m.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={SPRING}
            className="inline-flex items-center gap-2 rounded-full bg-[#00bbff]/15 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.16em] text-[#00bbff]"
          >
            <span className="size-2 rounded-full bg-[#00bbff]" />
            {POINTS_EARNED} points
            <span className="size-1 rounded-full bg-[#00bbff]" />
            level 2
          </m.div>
          <h1 className="mt-5 text-5xl font-black uppercase leading-[0.92] tracking-tight text-white md:text-6xl">
            Invite &amp; earn
          </h1>
          <p className="mt-3 text-sm font-medium text-zinc-400">
            {next
              ? `${next.points - POINTS_EARNED} points to unlock ${next.reward}`
              : "Every quest cleared. You're a legend."}
          </p>
        </div>

        {/* Roadmap stepper */}
        <div className="mt-10 space-y-3">
          {MILESTONES.map((milestone, i) => {
            const unlocked = isUnlocked(milestone);
            const isNext = next?.id === milestone.id;
            return (
              <m.div
                key={milestone.id}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ ...SPRING, delay: 0.05 * i }}
                className={cn(
                  "flex items-center gap-4 rounded-[22px] p-4 transition-colors",
                  unlocked
                    ? "bg-zinc-800"
                    : isNext
                      ? "bg-zinc-800/70 ring-2 ring-[#00bbff]/40"
                      : "bg-zinc-900/60",
                )}
              >
                <div
                  className={cn(
                    "flex size-16 shrink-0 items-center justify-center rounded-2xl",
                    unlocked ? "bg-[#00bbff]/15" : "bg-zinc-800/80",
                  )}
                >
                  <DevSticker
                    emoji={milestone.emoji}
                    size={40}
                    dimmed={!unlocked}
                    pulse={isNext}
                    pop={unlocked}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p
                      className={cn(
                        "truncate text-base font-bold",
                        unlocked ? "text-white" : "text-zinc-500",
                      )}
                    >
                      {milestone.label}
                    </p>
                    {unlocked ? (
                      <CheckmarkCircle02Icon
                        size={16}
                        className="shrink-0 text-[#06d6a0]"
                      />
                    ) : (
                      <LockIcon size={14} className="shrink-0 text-zinc-600" />
                    )}
                  </div>
                  <p className="text-xs font-medium text-zinc-500">
                    {milestone.points} points
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-3 py-1.5 text-xs font-bold uppercase tracking-wide",
                    unlocked
                      ? "bg-[#06d6a0]/15 text-[#06d6a0]"
                      : "bg-zinc-800 text-zinc-500",
                  )}
                >
                  {milestone.reward}
                </span>
              </m.div>
            );
          })}
        </div>

        {/* Pill share card */}
        <div className="relative mt-10">
          <ConfettiBurst show={burst} />
          <div className="rounded-[28px] bg-zinc-800 p-5">
            <p className="text-center text-xs font-bold uppercase tracking-[0.16em] text-zinc-500">
              Drop your invite link
            </p>
            <div className="mt-3 flex items-center gap-2 rounded-full bg-zinc-900 p-1.5 pl-5">
              <span className="min-w-0 flex-1 truncate font-mono text-sm font-medium text-zinc-200">
                {INVITE_PATH}
              </span>
              <Button
                onPress={handleCopy}
                className={cn(
                  "h-11 shrink-0 gap-1.5 rounded-full px-6 font-bold",
                  copied
                    ? "bg-[#06d6a0] text-black"
                    : "bg-[#00bbff] text-black",
                )}
                startContent={
                  copied ? (
                    <CheckmarkCircle02Icon size={18} />
                  ) : (
                    <CopyIcon size={18} />
                  )
                }
              >
                {copied ? "Copied!" : "Copy"}
              </Button>
            </div>

            {/* Big circular channel buttons */}
            <div className="mt-5 flex justify-center gap-4">
              <RoundChannel
                icon={<WhatsappIcon size={22} />}
                bg="#25D366"
                onClick={() =>
                  window.open(buildWhatsAppUrl(), "_blank", "noopener")
                }
                label="WhatsApp"
              />
              <RoundChannel
                icon={<NewTwitterIcon size={20} />}
                bg="#ffffff"
                fg="#000000"
                onClick={() => window.open(buildXUrl(), "_blank", "noopener")}
                label="Post on X"
              />
              <RoundChannel
                icon={<Mail01Icon size={20} />}
                bg="#00bbff"
                fg="#000000"
                onClick={() => toast.success("Email composer opened")}
                label="Email"
              />
            </div>

            {/* Chunky email input */}
            <div className="mt-5 flex items-center gap-2">
              <Input
                value={email}
                onValueChange={setEmail}
                onKeyDown={onKey}
                placeholder="friend@email.com"
                variant="flat"
                classNames={{
                  inputWrapper:
                    "h-14 rounded-2xl bg-zinc-900 data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
                  input: "text-base font-medium text-zinc-100",
                }}
              />
              <Button
                onPress={sendInvite}
                className="h-14 shrink-0 gap-1.5 rounded-2xl bg-[#00bbff] px-6 font-bold text-black"
                startContent={<SentIcon size={18} />}
              >
                Send
              </Button>
            </div>
          </div>
        </div>

        {/* Mini leaderboard */}
        <div className="mt-10 rounded-[24px] bg-zinc-800 p-5">
          <div className="flex items-center gap-2">
            <RankingIcon size={18} className="text-[#ffd166]" />
            <p className="text-sm font-bold text-white">This week</p>
            <span className="ml-auto rounded-full bg-[#ffd166]/15 px-3 py-1 text-xs font-bold text-[#ffd166]">
              You&apos;re #12
            </span>
          </div>
          <div className="mt-4 space-y-1.5">
            {LEADERBOARD.map((row) => (
              <div
                key={row.rank}
                className={cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5",
                  row.isYou ? "bg-[#00bbff]/15" : "bg-zinc-900/40",
                )}
              >
                <span
                  className={cn(
                    "w-6 text-sm font-bold tabular-nums",
                    row.isYou ? "text-[#00bbff]" : "text-zinc-500",
                  )}
                >
                  {row.rank}
                </span>
                <span
                  className={cn(
                    "flex-1 text-sm font-semibold",
                    row.isYou ? "text-white" : "text-zinc-300",
                  )}
                >
                  {row.name}
                </span>
                <span className="font-mono text-sm font-bold tabular-nums text-zinc-400">
                  {row.points}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function RoundChannel({
  icon,
  bg,
  fg = "#ffffff",
  onClick,
  label,
}: {
  icon: React.ReactNode;
  bg: string;
  fg?: string;
  onClick: () => void;
  label: string;
}) {
  return (
    <m.button
      type="button"
      onClick={onClick}
      aria-label={label}
      whileTap={{ scale: 0.88 }}
      whileHover={{ y: -3 }}
      transition={SPRING}
      className="flex size-14 items-center justify-center rounded-full shadow-lg"
      style={{ background: bg, color: fg }}
    >
      {icon}
    </m.button>
  );
}
