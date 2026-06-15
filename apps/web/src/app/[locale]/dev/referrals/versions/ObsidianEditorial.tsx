"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  CopyIcon,
  Mail01Icon,
  NewTwitterIcon,
  WhatsappIcon,
} from "@icons";
import * as m from "motion/react-m";
import { type KeyboardEvent, useState } from "react";

import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { DevSticker } from "./DevSticker";
import {
  buildMailUrl,
  buildWhatsAppUrl,
  buildXUrl,
  EMAIL_PATTERN,
  INVITE_PATH,
  INVITE_URL,
  isUnlocked,
  MILESTONES,
  POINTS_EARNED,
  POINTS_GOAL,
} from "./mockData";
import { useCopyLink } from "./useCopyLink";

// ──────────────────────────────────────────────────────────────────────────
// Direction 2 — OBSIDIAN EDITORIAL
// Luxury invitation. Single centered column, pure black. Oversized serif hero
// over an iridescent bloom. One frosted share card. ONE slim progress bar with
// a single gift milestone. Cinematic, sparse, serif + grotesk. Clyde / Oku.
// ──────────────────────────────────────────────────────────────────────────

const EASE = [0.16, 1, 0.3, 1] as const;

export function ObsidianEditorial() {
  const { copied, copy } = useCopyLink(INVITE_URL);
  const [email, setEmail] = useState("");
  const pct = Math.min(100, Math.round((POINTS_EARNED / POINTS_GOAL) * 100));
  const giftMilestone = MILESTONES[0];

  const sendInvite = () => {
    const valid = email
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter a valid email address");
      return;
    }
    toast.success("Invitation sent");
    setEmail("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendInvite();
    }
  };

  return (
    <div className="relative min-h-full overflow-hidden bg-black">
      {/* Iridescent bloom behind the hero — soft, editorial, no cyan ring. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-center">
        <m.div
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.6, ease: EASE }}
          className="mt-[-160px] h-[460px] w-[460px] rounded-full blur-[90px]"
          style={{
            background:
              "conic-gradient(from 210deg at 50% 50%, rgba(0,187,255,0.30), rgba(168,85,247,0.22), rgba(244,114,182,0.18), rgba(0,187,255,0.30))",
          }}
        />
      </div>

      <div className="relative mx-auto flex max-w-xl flex-col items-center px-6 py-24 text-center">
        {/* Floating gift orb */}
        <m.div
          initial={{ opacity: 0, y: 18, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.9, ease: EASE }}
        >
          <m.div
            animate={{ y: [0, -8, 0] }}
            transition={{
              duration: 5,
              repeat: Number.POSITIVE_INFINITY,
              ease: "easeInOut",
            }}
          >
            <DevSticker emoji="🎁" size={88} pop />
          </m.div>
        </m.div>

        <m.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: EASE }}
          className="mt-10 text-[11px] font-medium uppercase tracking-[0.32em] text-zinc-500"
        >
          An invitation from GAIA
        </m.p>

        <m.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.25, ease: EASE }}
          className="mt-5 font-serif text-6xl font-normal leading-[0.98] tracking-tight text-white md:text-7xl"
        >
          Bring your
          <br />
          people.
        </m.h1>

        <m.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4, ease: EASE }}
          className="mt-6 max-w-md text-base leading-relaxed text-zinc-400"
        >
          Give a friend 50% off their first two months. When they join, a month
          of PRO is quietly added to your account.
        </m.p>

        {/* One frosted share card */}
        <m.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.55, ease: EASE }}
          className="mt-12 w-full rounded-3xl bg-zinc-800/40 p-2 backdrop-blur-xl"
        >
          <div className="flex items-center gap-2">
            <div className="flex h-14 min-w-0 flex-1 items-center rounded-2xl bg-black/40 px-5">
              <span className="truncate font-mono text-sm tracking-tight text-zinc-300">
                {INVITE_PATH}
              </span>
            </div>
            <Button
              onPress={copy}
              className={cn(
                "h-14 shrink-0 gap-2 rounded-2xl px-6 font-medium transition-colors",
                copied
                  ? "bg-white text-black"
                  : "bg-white/10 text-white data-[hover=true]:bg-white/15",
              )}
              startContent={
                copied ? (
                  <CheckmarkCircle02Icon size={18} />
                ) : (
                  <CopyIcon size={18} />
                )
              }
            >
              {copied ? "Copied" : "Copy link"}
            </Button>
          </div>

          {/* Quiet channel row */}
          <div className="mt-2 flex items-center gap-1 px-2 py-1">
            <QuietChannel
              icon={<WhatsappIcon size={15} />}
              label="WhatsApp"
              onClick={() =>
                window.open(buildWhatsAppUrl(), "_blank", "noopener")
              }
            />
            <QuietChannel
              icon={<NewTwitterIcon size={15} />}
              label="X"
              onClick={() => window.open(buildXUrl(), "_blank", "noopener")}
            />
            <QuietChannel
              icon={<Mail01Icon size={15} />}
              label="Mail"
              onClick={() => window.open(buildMailUrl(), "_blank", "noopener")}
            />
          </div>
        </m.div>

        {/* Email invite line */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.65, ease: EASE }}
          className="mt-4 flex w-full items-center gap-2"
        >
          <Input
            value={email}
            onValueChange={setEmail}
            onKeyDown={onKey}
            placeholder="Invite by email"
            variant="flat"
            classNames={{
              inputWrapper:
                "h-14 rounded-2xl bg-zinc-900/60 data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
              input: "text-sm text-zinc-100 placeholder:text-zinc-600",
            }}
          />
          <Button
            isIconOnly
            onPress={sendInvite}
            className="h-14 w-14 shrink-0 rounded-2xl bg-white text-black data-[hover=true]:bg-zinc-200"
            aria-label="Send invitation"
          >
            <ArrowRight01Icon size={20} />
          </Button>
        </m.div>

        {/* Single slim progress bar with one gift milestone */}
        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="mt-16 w-full max-w-sm"
        >
          <div className="mb-3 flex items-center justify-between text-xs">
            <span className="text-zinc-500">Next reward</span>
            <span className="font-medium text-zinc-300">
              {giftMilestone.reward}
            </span>
          </div>
          <div className="relative h-px w-full bg-zinc-800">
            <m.div
              initial={{ scaleX: 0 }}
              animate={{ scaleX: pct / 100 }}
              transition={{ duration: 1.4, delay: 0.9, ease: EASE }}
              style={{ originX: 0 }}
              className="absolute inset-0 bg-gradient-to-r from-zinc-400 to-white"
            />
            <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2">
              <DevSticker
                emoji={giftMilestone.emoji}
                size={26}
                dimmed={!isUnlocked(giftMilestone)}
              />
            </div>
          </div>
          <p className="mt-12 text-xs tracking-wide text-zinc-600">
            Joined by 2,400 members
          </p>
        </m.div>
      </div>
    </div>
  );
}

function QuietChannel({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-xs font-medium text-zinc-500 transition-colors hover:text-white"
    >
      {icon}
      {label}
    </button>
  );
}
