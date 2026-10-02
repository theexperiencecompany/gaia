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
import { browserApi } from "@/features/browser/api/browserApi";
import {
  type PostHandoffDecision,
  type SettledHandoffStatus,
  useHandoffDecision,
} from "@/features/browser/hooks/useHandoffDecision";
import { useLiveBrowser } from "@/features/browser/hooks/useLiveBrowser";
import { useLiveView } from "@/features/browser/hooks/useLiveView";
import type { LiveSurface } from "@/features/browser/types";
import { useIsMobile } from "@/hooks/ui/useMobile";
import type {
  BrowserHandoffDecision,
  BrowserHandoffSnapshot,
  BrowserSensitiveCategory,
} from "@/types/features/browserTaskTypes";
import { LiveKeyboard } from "./LiveKeyboard";
import { LiveScreen } from "./LiveScreen";

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
  surface,
}: {
  handoff: BrowserHandoffSnapshot;
  surface: LiveSurface;
}) {
  const meta = HANDOFF_META[handoff.category ?? "none"];
  const Icon = meta.icon;
  const inline = surface.kind !== "panel";
  const isMobile = useIsMobile();
  const view = useLiveView(handoff.session_id, handoff.live_view_url);
  // The side panel already streams this session: no second socket here.
  const live = useLiveBrowser(inline ? view.socketUrl : null, true, view.renew);
  const post = (decision: BrowserHandoffDecision) =>
    browserApi.postHandoffDecision(handoff.handoff_id, decision);

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
      {inline && view.socketUrl && (
        <div className="mt-3 overflow-hidden rounded-xl bg-zinc-900">
          <LiveScreen live={live} interactive />
          {isMobile && live.status === "live" && (
            <div className="px-3 py-2">
              <LiveKeyboard live={live} />
            </div>
          )}
        </div>
      )}

      <HandoffDecision
        post={post}
        primary={
          surface.kind === "card" ? (
            <TakeOverButton cta={meta.cta} onPress={surface.openPanel} />
          ) : surface.kind === "mobile" && view.pageUrl ? (
            <TakeOverButton cta={meta.cta} href={view.pageUrl} />
          ) : null
        }
      />
    </div>
  );
}

/**
 * Three choices, in order of intent: an optional primary (take over), I'm done
 * (resume), stop the task. Once the user has chosen, the server's answer
 * replaces them. Shared with the bot user's live page, whose code authorizes
 * `post` and whose `trailing` slot carries the phone keyboard.
 */
export function HandoffDecision({
  post,
  primary,
  trailing,
}: {
  post: PostHandoffDecision;
  primary?: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  const { decide, decided, settled } = useHandoffDecision(post);
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
      {primary}
      <Button
        variant={primary ? "flat" : "solid"}
        radius="sm"
        className={`flex-1 font-semibold ${
          primary ? "text-zinc-100" : "bg-[#00bbff] text-zinc-900"
        }`}
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
      {trailing}
    </div>
  );
}

// "Take over": open the live browser — the side panel on desktop, the tokened
// page in a new tab on mobile.
function TakeOverButton({
  cta,
  onPress,
  href,
}: {
  cta: string;
  onPress?: () => void;
  href?: string;
}) {
  const className = "flex-1 bg-[#00bbff] font-semibold text-zinc-900";
  if (href) {
    return (
      <Button
        as="a"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        radius="sm"
        className={className}
      >
        {cta}
      </Button>
    );
  }
  return (
    <Button radius="sm" className={className} onPress={onPress}>
      {cta}
    </Button>
  );
}
