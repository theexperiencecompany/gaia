"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Spinner } from "@heroui/spinner";
import {
  Alert01Icon,
  CheckmarkCircle02Icon,
  CreditCardIcon,
  CursorInWindowIcon,
  ShieldUserIcon,
  SquareArrowUpRight02Icon,
  StopCircleIcon,
} from "@icons";
import { useState } from "react";
import {
  liveViewPageUrl,
  liveViewSocketUrl,
} from "@/features/browser/api/browserApi";
import type { SettledHandoffStatus } from "@/features/browser/hooks/useHandoffDecision";
import { useHandoffDecision } from "@/features/browser/hooks/useHandoffDecision";
import { useLiveViewToken } from "@/features/browser/hooks/useLiveViewToken";
import type {
  BrowserHandoffSnapshot,
  BrowserHandoffStatus,
  BrowserSensitiveCategory,
} from "@/types/features/browserTaskTypes";
import { LiveBrowserCanvas } from "./LiveBrowserCanvas";

// Each sensitive category gets an icon, a title that says what the user does,
// and a call-to-action for the button that opens the live browser.
const HANDOFF_META: Record<
  BrowserSensitiveCategory,
  {
    icon: React.ComponentType<{ className?: string }>;
    title: string;
    cta: string;
  }
> = {
  none: {
    icon: CursorInWindowIcon,
    title: "Take over for a moment",
    cta: "Take over",
  },
  payment: {
    icon: CreditCardIcon,
    title: "Finish the payment yourself",
    cta: "Take over",
  },
  credentials: {
    icon: ShieldUserIcon,
    title: "Sign in to continue",
    cta: "Take over",
  },
  irreversible: {
    icon: Alert01Icon,
    title: "Confirm this step to continue",
    cta: "Take over",
  },
};

// Resolved elsewhere (chat, another device) or after a reload — server status
// is the source of truth, so the card never sits on a stale "pending".
const RESOLVED_META: Record<
  Exclude<BrowserHandoffStatus, "pending">,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  completed: {
    icon: CheckmarkCircle02Icon,
    label: "Done, resuming the task.",
  },
  cancelled: { icon: StopCircleIcon, label: "Stopped." },
  timeout: { icon: StopCircleIcon, label: "Timed out, the task was stopped." },
};

export function HandoffPrompt({
  handoff,
  inPanel = false,
  onOpenPanel,
  onSettled,
}: {
  handoff: BrowserHandoffSnapshot;
  /** Rendered inside the browser side panel: the big interactive canvas is
   * already above, so skip the embedded canvas and the open-browser button. */
  inPanel?: boolean;
  /** Desktop web: the primary action opens the side panel instead of a new tab. */
  onOpenPanel?: () => void;
  /** Fires once when the handoff reaches a terminal status (this tab or elsewhere). */
  onSettled?: (status: SettledHandoffStatus) => void;
}) {
  const { decide, decided, pending, settled } = useHandoffDecision(
    handoff.handoff_id,
    onSettled,
  );
  const [note, setNote] = useState("");
  const meta = HANDOFF_META[handoff.category] ?? HANDOFF_META.none;
  const Icon = meta.icon;
  const liveToken = useLiveViewToken(handoff.session_id);
  const pageUrl =
    handoff.live_view_url && liveToken
      ? liveViewPageUrl(handoff.live_view_url, liveToken)
      : null;

  return (
    <div className="rounded-2xl bg-zinc-900 p-3.5">
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-[#00bbff]" />
        <p className="text-sm font-semibold text-zinc-100">{meta.title}</p>
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-zinc-400">
        {handoff.reason}
      </p>

      {/* On a sign-in handoff, reassure the user the login isn't wasted: the
          session is saved encrypted and reused so the next task skips it. Only
          for credentials — never payments/confirmations, which aren't stored. */}
      {handoff.category === "credentials" && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-zinc-500">
          Once you're signed in, I'll save this site's session — encrypted — so
          I can skip the login next time. You can remove saved sites anytime in
          your Browser settings.
        </p>
      )}

      {/* The canvas is the instruction — it says "you're in control" better than
          a label above it ever did, so the label is gone. */}
      {!inPanel && handoff.live_view_url && liveToken && (
        <div className="mt-3">
          <LiveBrowserCanvas
            socketUrl={liveViewSocketUrl(handoff.live_view_url, liveToken)}
            interactive
          />
        </div>
      )}

      {/* Settled beats the in-flight spinner: once the server confirms the
          decision, show the outcome — never an eternal "Stopping…". */}
      {settled ? (
        (() => {
          const resolved = RESOLVED_META[settled];
          const ResolvedIcon = resolved.icon;
          return (
            <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-zinc-300">
              <ResolvedIcon className="size-4" />
              {resolved.label}
            </div>
          );
        })()
      ) : decided ? (
        <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-zinc-300">
          <Spinner size="sm" color="current" />
          {decided === "continue" ? "Continuing…" : "Stopping…"}
        </div>
      ) : (
        <div className="mt-3 space-y-2.5 pt-1">
          {/* Three clear choices, in order of intent: take over (do it live),
              I'm done (resume), skip (give up on this step). "Take over" hides
              once you're already inside the panel — nothing left to open. */}
          <div className="flex items-center gap-2">
            {!inPanel && (onOpenPanel || pageUrl) && (
              <TakeOverButton
                cta={meta.cta}
                pageUrl={pageUrl}
                onOpenPanel={onOpenPanel}
              />
            )}
            <Button
              radius="full"
              className="flex-1 bg-zinc-100 font-semibold text-zinc-900 data-[hover=true]:bg-white"
              isLoading={pending}
              startContent={
                !pending ? (
                  <CheckmarkCircle02Icon className="size-4" />
                ) : undefined
              }
              onPress={() => decide("continue", note.trim() || undefined)}
            >
              I&rsquo;m done
            </Button>
            <Button
              variant="light"
              radius="full"
              className="shrink-0 px-3 text-zinc-500"
              isDisabled={pending}
              onPress={() => decide("cancel")}
            >
              Skip
            </Button>
          </div>

          <Input
            size="sm"
            radius="full"
            value={note}
            onValueChange={setNote}
            isDisabled={pending}
            aria-label="Note for the assistant"
            placeholder={'Or tell me what to do instead, e.g. "skip the login"'}
            classNames={{
              inputWrapper:
                "bg-zinc-800 data-[hover=true]:bg-zinc-800/80 group-data-[focus=true]:bg-zinc-800/80",
              input: "text-zinc-100 placeholder:text-zinc-500",
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                decide("continue", note.trim() || undefined);
              }
            }}
          />
        </div>
      )}
    </div>
  );
}

// "Take over": open the live browser — the side panel on desktop, the tokened
// page in a new tab on bots/mobile.
function TakeOverButton({
  cta,
  pageUrl,
  onOpenPanel,
}: {
  cta: string;
  pageUrl: string | null;
  onOpenPanel?: () => void;
}) {
  if (onOpenPanel) {
    return (
      <Button
        radius="full"
        className="flex-1 bg-[#00bbff] font-semibold text-zinc-900"
        endContent={<CursorInWindowIcon className="size-4" />}
        onPress={onOpenPanel}
      >
        {cta}
      </Button>
    );
  }
  if (pageUrl) {
    return (
      <Button
        as="a"
        href={pageUrl}
        target="_blank"
        rel="noopener noreferrer"
        radius="full"
        className="flex-1 bg-[#00bbff] font-semibold text-zinc-900"
        endContent={<SquareArrowUpRight02Icon className="size-4" />}
      >
        {cta}
      </Button>
    );
  }
  return null;
}
