"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  ArrowRight02Icon,
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
  buildWhatsAppUrl,
  buildXUrl,
  EMAIL_PATTERN,
  INVITE_CODE,
  INVITE_PATH,
  INVITE_URL,
  isUnlocked,
  MILESTONES,
  POINTS_EARNED,
  POINTS_GOAL,
} from "./mockData";
import { useCopyLink } from "./useCopyLink";

// ──────────────────────────────────────────────────────────────────────────
// Direction 4 — THE TICKET
// Every invite is a tear-off ticket. Centered. Hero = physical reward-ticket
// card with CSS notched / perforated edge. "GIVE $10 · GET $10" split across
// the perforation. Code as per-character tiles. Progress = row of "stamped"
// emoji-sticker stubs + thin bar. Warm-tinged dark, tactile inset, slight
// rotation, tear / stamp snap. Givingli / Empower / Chance AI.
// ──────────────────────────────────────────────────────────────────────────

const EASE = [0.16, 1, 0.3, 1] as const;
const NOTCH = "#161311"; // warm near-black for the punched notches

export function TheTicket() {
  const { copied, copy } = useCopyLink(INVITE_URL);
  const { copied: codeCopied, copy: copyCode } = useCopyLink(INVITE_CODE);
  const [email, setEmail] = useState("");
  const pct = Math.min(100, Math.round((POINTS_EARNED / POINTS_GOAL) * 100));
  // Stable per-slot identity so the tile keys never fall back to the array
  // index (the code can contain repeated characters).
  const codeTiles = INVITE_CODE.split("").map((char, position) => ({
    char,
    id: `slot-${position}-${char}`,
  }));

  const sendInvite = () => {
    const valid = email
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => EMAIL_PATTERN.test(e));
    if (valid.length === 0) {
      toast.error("Enter a valid email address");
      return;
    }
    toast.success("Ticket sent");
    setEmail("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendInvite();
    }
  };

  return (
    <div
      className="min-h-full px-6 py-16"
      style={{
        background:
          "radial-gradient(120% 80% at 50% -10%, #1a1512 0%, #121110 55%, #0e0d0c 100%)",
      }}
    >
      <div className="mx-auto flex max-w-md flex-col items-center">
        <p className="mb-8 text-[11px] font-semibold uppercase tracking-[0.3em] text-amber-200/40">
          Your invite ticket
        </p>

        {/* THE TICKET */}
        <m.div
          initial={{ opacity: 0, y: 24, rotate: -3 }}
          animate={{ opacity: 1, y: 0, rotate: -1.4 }}
          transition={{ duration: 0.8, ease: EASE }}
          whileHover={{ rotate: 0, y: -4 }}
          className="relative w-full select-none"
        >
          <div
            className="relative overflow-hidden rounded-[26px] p-px"
            style={{
              background:
                "linear-gradient(160deg, rgba(255,236,200,0.18), rgba(255,255,255,0.02) 40%, rgba(0,0,0,0.4))",
            }}
          >
            <div
              className="relative rounded-[25px] px-7 pb-7 pt-8"
              style={{
                background:
                  "linear-gradient(165deg, #2a221b 0%, #211b16 45%, #1a1512 100%)",
                boxShadow:
                  "inset 0 1px 0 rgba(255,236,200,0.12), inset 0 -30px 60px rgba(0,0,0,0.4)",
              }}
            >
              {/* Top split: GIVE $10 · GET $10 */}
              <div className="flex items-stretch">
                <div className="flex-1 text-center">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-amber-200/50">
                    Give
                  </p>
                  <p className="mt-1 font-serif text-4xl font-normal text-amber-50">
                    $10
                  </p>
                </div>
                <div className="flex items-center px-4">
                  <span className="size-1.5 rounded-full bg-amber-200/30" />
                </div>
                <div className="flex-1 text-center">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-amber-200/50">
                    Get
                  </p>
                  <p className="mt-1 font-serif text-4xl font-normal text-amber-50">
                    $10
                  </p>
                </div>
              </div>

              {/* Perforation / tear line with punched notches */}
              <div
                className="relative my-7 flex items-center"
                aria-hidden="true"
              >
                <div
                  className="absolute left-[-28px] size-7 rounded-full"
                  style={{ background: NOTCH }}
                />
                <div
                  className="absolute right-[-28px] size-7 rounded-full"
                  style={{ background: NOTCH }}
                />
                <div className="h-px flex-1 border-t-2 border-dashed border-amber-200/15" />
              </div>

              {/* Code as per-character tiles */}
              <p className="text-center text-[10px] font-semibold uppercase tracking-[0.24em] text-amber-200/50">
                Redeem code
              </p>
              <div className="mt-3 flex justify-center gap-1.5">
                {codeTiles.map((tile, i) => (
                  <m.span
                    key={tile.id}
                    initial={{ opacity: 0, y: 8, rotate: -8 }}
                    animate={{ opacity: 1, y: 0, rotate: 0 }}
                    transition={{
                      delay: 0.35 + i * 0.06,
                      type: "spring",
                      stiffness: 480,
                      damping: 18,
                    }}
                    className="flex h-11 w-9 items-center justify-center rounded-lg font-mono text-lg font-bold text-amber-50"
                    style={{
                      background: "rgba(0,0,0,0.35)",
                      boxShadow:
                        "inset 0 1px 0 rgba(255,236,200,0.1), inset 0 -2px 4px rgba(0,0,0,0.45)",
                    }}
                  >
                    {tile.char}
                  </m.span>
                ))}
              </div>

              <div className="mt-6 flex justify-center">
                <Button
                  size="sm"
                  onPress={copyCode}
                  className={cn(
                    "h-9 gap-1.5 rounded-full px-5 text-xs font-semibold",
                    codeCopied
                      ? "bg-amber-100 text-stone-900"
                      : "bg-amber-200/10 text-amber-100 data-[hover=true]:bg-amber-200/20",
                  )}
                  startContent={
                    codeCopied ? (
                      <CheckmarkCircle02Icon size={15} />
                    ) : (
                      <CopyIcon size={15} />
                    )
                  }
                >
                  {codeCopied ? "Code copied" : "Copy code"}
                </Button>
              </div>
            </div>
          </div>
        </m.div>

        {/* Link card */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: EASE }}
          className="mt-8 w-full rounded-2xl bg-stone-900/60 p-2 ring-1 ring-amber-200/5"
        >
          <div className="flex items-center gap-2">
            <div className="flex h-12 min-w-0 flex-1 items-center rounded-xl bg-black/30 px-4">
              <span className="truncate font-mono text-sm text-amber-100/80">
                {INVITE_PATH}
              </span>
            </div>
            <Button
              isIconOnly
              onPress={copy}
              aria-label="Copy invite link"
              className={cn(
                "h-12 w-12 shrink-0 rounded-xl",
                copied
                  ? "bg-amber-100 text-stone-900"
                  : "bg-amber-200/10 text-amber-100 data-[hover=true]:bg-amber-200/20",
              )}
            >
              {copied ? (
                <CheckmarkCircle02Icon size={18} />
              ) : (
                <CopyIcon size={18} />
              )}
            </Button>
          </div>
          <div className="mt-2 flex gap-2">
            <TicketChannel
              icon={<WhatsappIcon size={16} />}
              label="WhatsApp"
              onClick={() =>
                window.open(buildWhatsAppUrl(), "_blank", "noopener")
              }
            />
            <TicketChannel
              icon={<NewTwitterIcon size={15} />}
              label="X"
              onClick={() => window.open(buildXUrl(), "_blank", "noopener")}
            />
            <TicketChannel
              icon={<Mail01Icon size={15} />}
              label="Email"
              onClick={() => toast.success("Email composer opened")}
            />
          </div>
        </m.div>

        {/* Email field */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.4, ease: EASE }}
          className="mt-3 flex w-full items-center gap-2"
        >
          <Input
            value={email}
            onValueChange={setEmail}
            onKeyDown={onKey}
            placeholder="Send a ticket to a friend"
            variant="flat"
            classNames={{
              inputWrapper:
                "h-12 rounded-xl bg-stone-900/60 data-[hover=true]:bg-stone-900 group-data-[focus=true]:bg-stone-900",
              input: "text-sm text-amber-50 placeholder:text-amber-200/30",
            }}
          />
          <Button
            isIconOnly
            onPress={sendInvite}
            aria-label="Send ticket"
            className="h-12 w-12 shrink-0 rounded-xl bg-amber-100 text-stone-900 data-[hover=true]:bg-amber-50"
          >
            <ArrowRight02Icon size={20} />
          </Button>
        </m.div>

        {/* Progress = stamped emoji stubs + thin bar */}
        <div className="mt-12 w-full">
          <div className="flex items-center justify-between">
            {MILESTONES.map((milestone) => {
              const unlocked = isUnlocked(milestone);
              return (
                <div
                  key={milestone.id}
                  className="flex flex-col items-center"
                  style={{ rotate: `${unlocked ? -6 : 0}deg` }}
                >
                  <div
                    className={cn(
                      "flex size-14 items-center justify-center rounded-full",
                      unlocked
                        ? "bg-amber-200/[0.07] ring-1 ring-amber-200/20"
                        : "bg-black/20 ring-1 ring-white/[0.03]",
                    )}
                  >
                    <DevSticker
                      emoji={milestone.emoji}
                      size={32}
                      dimmed={!unlocked}
                      pop={unlocked}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="relative mt-4 h-1 w-full overflow-hidden rounded-full bg-black/40">
            <m.div
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 1.3, delay: 0.5, ease: EASE }}
              className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-300 to-amber-100"
            />
          </div>
          <p className="mt-3 text-center text-xs text-amber-200/40">
            {POINTS_EARNED} of {POINTS_GOAL} points stamped
          </p>
        </div>
      </div>
    </div>
  );
}

function TicketChannel({
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
      className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-black/20 py-2.5 text-xs font-medium text-amber-100/70 transition-colors hover:bg-black/40 hover:text-amber-50"
    >
      {icon}
      {label}
    </button>
  );
}
