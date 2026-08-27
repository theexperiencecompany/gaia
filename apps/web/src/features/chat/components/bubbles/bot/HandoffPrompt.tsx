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
    cta: "Open the live browser",
  },
  payment: {
    icon: CreditCardIcon,
    title: "Finish the payment yourself",
    cta: "Open the browser to pay",
  },
  credentials: {
    icon: ShieldUserIcon,
    title: "Sign in to continue",
    cta: "Open the browser to sign in",
  },
  irreversible: {
    icon: Alert01Icon,
    title: "Confirm this step to continue",
    cta: "Open the browser to confirm",
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

// The step-appropriate primary action: first "open the live browser" (side
// panel on desktop, tokened page on bots/mobile), then — once opened, or when
// already inside the panel — the confirm that resumes the agent.
function HandoffPrimaryAction({
  showOpen,
  cta,
  pageUrl,
  onOpenPanel,
  onOpened,
  pending,
  hasNote,
  onContinue,
}: {
  showOpen: boolean;
  cta: string;
  pageUrl: string | null;
  onOpenPanel?: () => void;
  onOpened: () => void;
  pending: boolean;
  hasNote: boolean;
  onContinue: () => void;
}) {
  if (showOpen && onOpenPanel) {
    return (
      <Button
        radius="full"
        className="w-full bg-[#00bbff] font-semibold text-zinc-900"
        endContent={<CursorInWindowIcon className="size-4" />}
        onPress={() => {
          onOpened();
          onOpenPanel();
        }}
      >
        {cta}
      </Button>
    );
  }
  if (showOpen && pageUrl) {
    return (
      <Button
        as="a"
        href={pageUrl}
        target="_blank"
        rel="noopener noreferrer"
        radius="full"
        className="w-full bg-[#00bbff] font-semibold text-zinc-900"
        endContent={<SquareArrowUpRight02Icon className="size-4" />}
        onPress={onOpened}
      >
        {cta}
      </Button>
    );
  }
  return (
    <Button
      radius="full"
      className="w-full bg-[#00bbff] font-semibold text-zinc-900"
      isLoading={pending}
      startContent={
        !pending ? <CheckmarkCircle02Icon className="size-4" /> : undefined
      }
      onPress={onContinue}
    >
      {hasNote ? "Send note and continue" : "I'm done, continue"}
    </Button>
  );
}

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
  // The primary action starts as "open the full browser"; only once the user has
  // actually opened it does the confirm ("Done") make sense as the next step.
  const [opened, setOpened] = useState(false);
  const meta = HANDOFF_META[handoff.category] ?? HANDOFF_META.none;
  const Icon = meta.icon;
  const liveToken = useLiveViewToken(handoff.session_id);
  const pageUrl =
    handoff.live_view_url && liveToken
      ? liveViewPageUrl(handoff.live_view_url, liveToken)
      : null;
  const hasNote = note.trim().length > 0;

  return (
    <div className="rounded-2xl bg-zinc-900 p-3.5">
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-[#00bbff]" />
        <p className="text-sm font-semibold text-zinc-100">{meta.title}</p>
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-zinc-400">
        {handoff.reason}
      </p>

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
          <HandoffPrimaryAction
            showOpen={!inPanel && !opened}
            cta={meta.cta}
            pageUrl={pageUrl}
            onOpenPanel={onOpenPanel}
            onOpened={() => setOpened(true)}
            pending={pending}
            hasNote={hasNote}
            onContinue={() => decide("continue", note.trim() || undefined)}
          />

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

          {/* Stop is the rare, destructive path — quiet text, not a peer of the
              primary action it sits under. */}
          <div className="flex justify-center">
            <Button
              variant="light"
              size="sm"
              radius="full"
              className="h-7 text-xs text-zinc-500"
              startContent={<StopCircleIcon className="size-3.5" />}
              onPress={() => decide("cancel")}
            >
              Stop the task
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
