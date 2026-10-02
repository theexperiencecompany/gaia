"use client";

import Image from "next/image";
import {
  browserApi,
  livePageSocketUrl,
} from "@/features/browser/api/browserApi";
import {
  type LiveStatus,
  useLiveBrowser,
} from "@/features/browser/hooks/useLiveBrowser";
import { useIsMobile } from "@/hooks/ui/useMobile";
import type { BrowserHandoffDecision } from "@/types/features/browserTaskTypes";
import { HandoffDecision } from "../bubbles/bot/HandoffPrompt";
import { LiveKeyboard } from "../bubbles/bot/LiveKeyboard";
import { LiveScreen } from "../bubbles/bot/LiveScreen";

const STATUS_LABEL: Record<LiveStatus, { label: string; dot: string }> = {
  connecting: { label: "Connecting…", dot: "bg-amber-500" },
  live: { label: "Live, you're in control", dot: "bg-emerald-500" },
  closed: { label: "Session ended", dot: "bg-red-500" },
};

interface LiveViewPageProps {
  /** The bot link's capability code, or a session id `token` authorizes. */
  code: string;
  /** A takeover token: the web card's "open" link. Absent on a bot link. */
  token: string | null;
}

/**
 * The live browser full screen, for a user with no web session: a bot user
 * opening their handoff link, or the web card opened in a new tab. Same
 * screen, input and decision as the chat card; a bot link's code also answers
 * the handoff it was sent for (I'm done / Stop task), a token link does not.
 */
export function LiveViewPage({ code, token }: LiveViewPageProps) {
  const isMobile = useIsMobile();
  const live = useLiveBrowser(livePageSocketUrl(code, token), true);
  const status = STATUS_LABEL[live.status];
  const keyboard =
    isMobile && live.status === "live" ? (
      <LiveKeyboard live={live} className="shrink-0" />
    ) : null;
  const post = (decision: BrowserHandoffDecision) =>
    browserApi.postLiveDecision(code, decision);
  const controls = token ? (
    keyboard
  ) : (
    <HandoffDecision
      post={post}
      trailing={keyboard}
      canDecide={live.status !== "closed"}
    />
  );

  return (
    <div className="flex h-dvh flex-col bg-zinc-950 text-zinc-200">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2.5 px-4 py-3">
        <Image
          src="/brand/gaia_wordmark_white.png"
          alt="GAIA"
          width={82}
          height={24}
          priority
          className="mr-auto h-6 w-auto"
        />
        <div className="flex items-center gap-2 whitespace-nowrap text-[13px] text-zinc-400 sm:order-last">
          <span className={`size-2 rounded-full ${status.dot}`} />
          {status.label}
        </div>
        {/* On a phone the controls take a row of their own under the brand. */}
        {controls && <div className="basis-full sm:basis-auto">{controls}</div>}
      </header>
      <main className="flex min-h-0 flex-1 items-start justify-center overflow-y-auto px-3.5 pb-3.5">
        <div className="w-full max-w-6xl overflow-hidden rounded-xl bg-zinc-900">
          <LiveScreen live={live} interactive />
        </div>
      </main>
    </div>
  );
}
