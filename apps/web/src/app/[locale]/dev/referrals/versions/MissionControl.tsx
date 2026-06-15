"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  ArrowUpRight01Icon,
  CheckmarkCircle02Icon,
  CopyIcon,
  Mail01Icon,
  NewTwitterIcon,
  SentIcon,
  UserGroupIcon,
  WhatsappIcon,
} from "@icons";
import { animate, useMotionValue, useTransform } from "motion/react";
import * as m from "motion/react-m";
import { type KeyboardEvent, useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
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
  nextMilestone,
  POINTS_EARNED,
  POINTS_GOAL,
  STATS,
} from "./mockData";
import { useCopyLink } from "./useCopyLink";

// ──────────────────────────────────────────────────────────────────────────
// Direction 1 — MISSION CONTROL
// Telemetry dashboard. Near-black two-column. Numbers count up on mount.
// Single accent (#00bbff). Full-width segmented milestone track. Monochrome,
// restrained, Linear/Fey/Wise energy.
// ──────────────────────────────────────────────────────────────────────────

function CountUp({
  to,
  className,
  duration = 1.4,
}: {
  to: number;
  className?: string;
  duration?: number;
}) {
  const count = useMotionValue(0);
  const rounded = useTransform(count, (v) => Math.round(v).toLocaleString());
  useEffect(() => {
    const controls = animate(count, to, {
      duration,
      ease: [0.16, 1, 0.3, 1],
    });
    return controls.stop;
  }, [count, to, duration]);
  return <m.span className={className}>{rounded}</m.span>;
}

function StatCard({
  label,
  value,
  hint,
  delay,
}: {
  label: string;
  value: number;
  hint: string;
  delay: number;
}) {
  return (
    <m.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-2xl bg-zinc-800 p-4"
    >
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-zinc-500">
        {label}
      </p>
      <p className="mt-2 font-mono text-3xl font-semibold tabular-nums text-zinc-100">
        <CountUp to={value} duration={1.1} />
      </p>
      <p className="mt-1 text-xs text-zinc-500">{hint}</p>
    </m.div>
  );
}

export function MissionControl() {
  const { copied, copy } = useCopyLink(INVITE_URL);
  const [email, setEmail] = useState("");
  const next = nextMilestone();
  const pct = Math.min(100, Math.round((POINTS_EARNED / POINTS_GOAL) * 100));

  const sendInvite = () => {
    const valid = email
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter at least one valid email");
      return;
    }
    toast.success(
      `Invite queued for ${valid.length} friend${valid.length > 1 ? "s" : ""}`,
    );
    setEmail("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendInvite();
    }
  };

  return (
    <div className="min-h-full bg-[#0c0c0d] px-6 py-12 md:px-12 md:py-16">
      <div className="mx-auto max-w-5xl">
        {/* Eyebrow */}
        <m.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-10 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.22em] text-zinc-500"
        >
          <span className="size-1.5 rounded-full bg-[#00bbff]" />
          Referral telemetry
        </m.div>

        <div className="grid gap-10 md:grid-cols-[1.1fr_0.9fr] md:gap-12">
          {/* LEFT — giant earned amount + share zone */}
          <div>
            <p className="text-sm text-zinc-500">Points earned</p>
            <div className="mt-1 flex items-end gap-3">
              <CountUp
                to={POINTS_EARNED}
                className="font-mono text-7xl font-semibold leading-none tracking-tight text-white tabular-nums md:text-8xl"
              />
              <span className="mb-2 text-lg font-medium text-zinc-600">
                / {POINTS_GOAL}
              </span>
            </div>
            <p className="mt-3 max-w-sm text-sm leading-relaxed text-zinc-400">
              {next
                ? `${next.points - POINTS_EARNED} points from ${next.reward} — every friend who joins moves the needle.`
                : "Every reward unlocked. You're maxed out."}
            </p>

            {/* Share surface */}
            <div className="mt-8 rounded-2xl bg-zinc-800 p-4">
              <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-zinc-500">
                Your invite link
              </p>
              <div className="mt-3 flex items-center gap-2">
                <div className="flex h-12 min-w-0 flex-1 items-center rounded-xl bg-zinc-900 px-4">
                  <span className="truncate font-mono text-sm text-zinc-300">
                    {INVITE_PATH}
                  </span>
                </div>
                <RaisedButton
                  type="button"
                  onClick={copy}
                  className="h-12 shrink-0 gap-1.5 px-5 font-semibold text-black"
                >
                  {copied ? (
                    <CheckmarkCircle02Icon size={18} />
                  ) : (
                    <CopyIcon size={18} />
                  )}
                  {copied ? "Copied" : "Copy"}
                </RaisedButton>
              </div>

              <div className="mt-3 grid grid-cols-3 gap-2">
                <ChannelButton
                  icon={<WhatsappIcon size={16} />}
                  label="WhatsApp"
                  onClick={() =>
                    window.open(buildWhatsAppUrl(), "_blank", "noopener")
                  }
                />
                <ChannelButton
                  icon={<NewTwitterIcon size={16} />}
                  label="Post on X"
                  onClick={() => window.open(buildXUrl(), "_blank", "noopener")}
                />
                <ChannelButton
                  icon={<Mail01Icon size={16} />}
                  label="Email"
                  onClick={() =>
                    window.open(buildMailUrl(), "_blank", "noopener")
                  }
                />
              </div>

              <div className="mt-3 flex items-center gap-2">
                <Input
                  value={email}
                  onValueChange={setEmail}
                  onKeyDown={onKey}
                  placeholder="friend@email.com"
                  variant="flat"
                  classNames={{
                    inputWrapper:
                      "h-12 bg-zinc-900 data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
                    input: "text-sm text-zinc-100",
                  }}
                />
                <Button
                  className="h-12 shrink-0 bg-zinc-700 px-4 font-semibold text-zinc-100 data-[hover=true]:bg-zinc-600"
                  onPress={sendInvite}
                  startContent={<SentIcon size={16} />}
                >
                  Send
                </Button>
              </div>
            </div>
          </div>

          {/* RIGHT — elevated stat-card grid */}
          <div className="grid grid-cols-2 gap-3 self-start">
            <StatCard
              label="Invited"
              value={STATS.invited}
              hint="links opened"
              delay={0.1}
            />
            <StatCard
              label="Joined"
              value={STATS.joined}
              hint="signed up"
              delay={0.18}
            />
            <StatCard
              label="Upgraded"
              value={STATS.upgraded}
              hint="went PRO"
              delay={0.26}
            />
            <m.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.34,
                duration: 0.5,
                ease: [0.16, 1, 0.3, 1],
              }}
              className="flex flex-col justify-between rounded-2xl bg-[#00bbff] p-4 text-black"
            >
              <div className="flex items-center justify-between">
                <UserGroupIcon size={20} />
                <ArrowUpRight01Icon size={18} className="opacity-70" />
              </div>
              <div>
                <p className="font-mono text-2xl font-semibold tabular-nums">
                  +{STATS.joined * 20 + STATS.upgraded * 30}
                </p>
                <p className="text-xs font-medium opacity-80">
                  points this month
                </p>
              </div>
            </m.div>
          </div>
        </div>

        {/* FULL-WIDTH segmented milestone track */}
        <div className="mt-14">
          <div className="mb-5 flex items-baseline justify-between">
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-zinc-500">
              Milestone track
            </p>
            <p className="font-mono text-xs text-zinc-500">{pct}% to crown</p>
          </div>

          <div className="relative">
            {/* base rail */}
            <div className="absolute left-0 right-0 top-[22px] h-[3px] rounded-full bg-zinc-800" />
            {/* filled rail */}
            <m.div
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{
                duration: 1.3,
                ease: [0.16, 1, 0.3, 1],
                delay: 0.3,
              }}
              className="absolute left-0 top-[22px] h-[3px] rounded-full bg-[#00bbff]"
            />
            <div className="relative flex justify-between">
              {MILESTONES.map((milestone) => {
                const unlocked = isUnlocked(milestone);
                const isNext = next?.id === milestone.id;
                return (
                  <div
                    key={milestone.id}
                    className="flex w-24 flex-col items-center text-center"
                  >
                    <div
                      className={cn(
                        "flex size-11 items-center justify-center rounded-full transition-colors",
                        unlocked ? "bg-zinc-900" : "bg-zinc-900/60",
                      )}
                    >
                      <DevSticker
                        emoji={milestone.emoji}
                        size={30}
                        dimmed={!unlocked}
                        pulse={isNext}
                        pop={unlocked}
                      />
                    </div>
                    <p
                      className={cn(
                        "mt-3 text-xs font-medium",
                        unlocked ? "text-zinc-200" : "text-zinc-600",
                      )}
                    >
                      {milestone.reward}
                    </p>
                    <p className="mt-0.5 font-mono text-[11px] text-zinc-600">
                      {milestone.points} pts
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChannelButton({
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
      className="inline-flex h-11 items-center justify-center gap-1.5 rounded-xl bg-zinc-900 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-700 hover:text-white"
    >
      {icon}
      {label}
    </button>
  );
}
