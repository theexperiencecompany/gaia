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
import { useEffect, useState } from "react";
import {
  browserApi,
  liveViewPageUrl,
  liveViewSocketUrl,
} from "@/features/browser/api/browserApi";
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
        color="warning"
        radius="full"
        className="w-full font-semibold"
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
        color="warning"
        radius="full"
        className="w-full font-semibold"
        endContent={<SquareArrowUpRight02Icon className="size-4" />}
        onPress={onOpened}
      >
        {cta}
      </Button>
    );
  }
  return (
    <Button
      color="warning"
      radius="full"
      className="w-full font-semibold"
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
}: {
  handoff: BrowserHandoffSnapshot;
  /** Rendered inside the browser side panel: the big interactive canvas is
   * already above, so skip the embedded canvas and the open-browser button. */
  inPanel?: boolean;
  /** Desktop web: the primary action opens the side panel instead of a new tab. */
  onOpenPanel?: () => void;
}) {
  const [decided, setDecided] = useState<"continue" | "cancel" | null>(null);
  const [pending, setPending] = useState(false);
  const [serverStatus, setServerStatus] = useState<BrowserHandoffStatus | null>(
    null,
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

  const settled = serverStatus && serverStatus !== "pending";

  useEffect(() => {
    if (decided || settled) return;
    let active = true;
    const poll = async () => {
      const res = await browserApi.getHandoffStatus(handoff.handoff_id);
      if (active && res && res.status !== "pending")
        setServerStatus(res.status);
    };
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [decided, settled, handoff.handoff_id]);

  const decide = async (decision: "continue" | "cancel", message?: string) => {
    setPending(true);
    setDecided(decision);
    try {
      await browserApi.postHandoffDecision(
        handoff.handoff_id,
        decision,
        message,
      );
    } catch {
      setDecided(null);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="rounded-2xl bg-amber-950/30 p-3.5 ring-1 ring-amber-500/25">
      <div className="flex items-start gap-2.5">
        <span className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
          <Icon className="size-4 text-amber-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-amber-50">{meta.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-amber-200/60">
            {handoff.reason}
          </p>
        </div>
      </div>

      {!inPanel && handoff.live_view_url && liveToken && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center gap-1.5 px-0.5">
            <CursorInWindowIcon className="size-3.5 text-amber-300/70" />
            <span className="text-[11px] font-medium text-amber-200/60">
              Live browser, you're in control
            </span>
          </div>
          <LiveBrowserCanvas
            socketUrl={liveViewSocketUrl(handoff.live_view_url, liveToken)}
            interactive
          />
        </div>
      )}

      {decided ? (
        <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-amber-200/80">
          <Spinner size="sm" color="warning" />
          {decided === "continue" ? "Continuing…" : "Stopping…"}
        </div>
      ) : serverStatus && serverStatus !== "pending" ? (
        (() => {
          const resolved = RESOLVED_META[serverStatus];
          const ResolvedIcon = resolved.icon;
          return (
            <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-amber-200/80">
              <ResolvedIcon className="size-4" />
              {resolved.label}
            </div>
          );
        })()
      ) : (
        <div className="mt-3 space-y-2.5 border-t border-amber-500/15 pt-3">
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

          <div className="flex items-center gap-2">
            <Input
              size="sm"
              radius="full"
              value={note}
              onValueChange={setNote}
              isDisabled={pending}
              aria-label="Note for the assistant"
              placeholder={'Or tell me what to do, e.g. "just grab the photo"'}
              classNames={{
                inputWrapper:
                  "bg-black/25 data-[hover=true]:bg-black/35 group-data-[focus=true]:bg-black/35",
                input: "text-amber-50 placeholder:text-amber-200/35",
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  decide("continue", note.trim() || undefined);
                }
              }}
            />
            <Button
              variant="light"
              size="sm"
              radius="full"
              className="shrink-0 text-amber-200/50"
              startContent={<StopCircleIcon className="size-4" />}
              onPress={() => decide("cancel")}
            >
              Stop
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
