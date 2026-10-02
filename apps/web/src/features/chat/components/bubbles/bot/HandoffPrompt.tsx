"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import {
  Alert01Icon,
  CheckmarkCircle02Icon,
  ComputerRemoveIcon,
  CreditCardIcon,
  CursorInWindowIcon,
  ShieldUserIcon,
  StopCircleIcon,
} from "@icons";
import {
  type SettledHandoffStatus,
  useHandoffDecision,
} from "@/features/browser/hooks/useHandoffDecision";
import { useLiveView } from "@/features/browser/hooks/useLiveView";
import type {
  BrowserHandoffSnapshot,
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

// The server's answer to the user's own decision, shown until the run's
// resolved handoff snapshot replaces the prompt.
const RESOLVED_META: Record<
  SettledHandoffStatus,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  completed: {
    icon: CheckmarkCircle02Icon,
    label: "Done, resuming the task.",
  },
  cancelled: { icon: StopCircleIcon, label: "Stopped." },
  timeout: { icon: StopCircleIcon, label: "Timed out, the task was stopped." },
  // The browser the user was sent to died while it waited on them.
  failed: { icon: ComputerRemoveIcon, label: "The browser closed." },
};

/**
 * The one ask when the browser run hands a step to the user, in the chat card
 * and in the action bar under the side panel's live screen. The run's own
 * handoff snapshot says when it resolved (here, in chat, or on another
 * device); the prompt is unmounted then.
 */
export function HandoffPrompt({
  handoff,
  inPanel = false,
  onOpenPanel,
}: {
  handoff: BrowserHandoffSnapshot;
  /** The live browser is in the side panel: skip the embedded canvas and the take-over button. */
  inPanel?: boolean;
  /** Desktop web: the primary action opens the side panel instead of a new tab. */
  onOpenPanel?: () => void;
}) {
  const meta = HANDOFF_META[handoff.category ?? "none"];
  const Icon = meta.icon;
  const live = useLiveView(handoff.session_id, handoff.live_view_url);

  return (
    <div className="rounded-2xl bg-zinc-900 p-3.5">
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-[#00bbff]" />
        <p className="text-sm font-semibold text-zinc-100">{meta.title}</p>
      </div>
      <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-zinc-400">
        {handoff.reason}
      </p>

      {/* Reassure the user a sign-in isn't wasted, only when the run will
          really keep it: never for payments/confirmations, never with login
          persistence off. */}
      {handoff.saves_login && (
        <p className="mt-1 text-[12px] text-zinc-500">
          Saved encrypted so next time skips the login.
        </p>
      )}

      {/* The canvas is the instruction — it says "you're in control" better than
          a label above it ever did. */}
      {!inPanel && live.socketUrl && (
        <div className="mt-3">
          <LiveBrowserCanvas
            socketUrl={live.socketUrl}
            interactive
            onDropped={live.renew}
          />
        </div>
      )}

      <HandoffActions
        handoffId={handoff.handoff_id}
        takeOver={
          !inPanel && (onOpenPanel || live.pageUrl) ? (
            <TakeOverButton
              cta={meta.cta}
              pageUrl={live.pageUrl}
              onOpenPanel={onOpenPanel}
            />
          ) : null
        }
      />
    </div>
  );
}

// Three choices, in order of intent: take over (do it live), I'm done (resume),
// stop the task. Once the user has chosen, the server's answer replaces them.
function HandoffActions({
  handoffId,
  takeOver,
}: {
  handoffId: string;
  takeOver: React.ReactNode;
}) {
  const { decide, decided, settled } = useHandoffDecision(handoffId);
  if (settled) {
    const resolved = RESOLVED_META[settled];
    const ResolvedIcon = resolved.icon;
    return (
      <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-zinc-300">
        <ResolvedIcon className="size-4" />
        {resolved.label}
      </div>
    );
  }
  if (decided) {
    return (
      <div className="mt-3 flex items-center gap-2 px-0.5 text-xs text-zinc-300">
        <Spinner size="sm" color="current" />
        {decided === "continue" ? "Continuing…" : "Stopping…"}
      </div>
    );
  }
  return (
    <div className="mt-3 flex items-center gap-2 pt-1">
      {takeOver}
      <Button
        variant="flat"
        radius="sm"
        className="flex-1 font-semibold text-zinc-100"
        onPress={() => decide("continue")}
      >
        I&rsquo;m done
      </Button>
      <Button
        variant="light"
        radius="sm"
        className="shrink-0 px-3 text-zinc-500"
        onPress={() => decide("cancel")}
      >
        Stop task
      </Button>
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
        radius="sm"
        className="flex-1 bg-[#00bbff] font-semibold text-zinc-900"
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
        radius="sm"
        className="flex-1 bg-[#00bbff] font-semibold text-zinc-900"
      >
        {cta}
      </Button>
    );
  }
  return null;
}
