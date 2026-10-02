"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import {
  AiWebBrowsingIcon,
  Cancel01Icon,
  SquareArrowUpRight02Icon,
  SquareLock02Icon,
} from "@icons";
import Image from "next/image";
import { useEffect, useState } from "react";
import {
  type LiveStatus,
  useLiveBrowser,
} from "@/features/browser/hooks/useLiveBrowser";
import { useLiveView } from "@/features/browser/hooks/useLiveView";
import { useBrowserPanel } from "@/features/browser/stores/browserPanelStore";
import { BROWSER_STATUS_META } from "@/features/browser/utils";
import type { BrowserHandoffSnapshot } from "@/types/features/browserTaskTypes";
import { HandoffPrompt } from "../bubbles/bot/HandoffPrompt";
import { ShimmerText } from "../bubbles/bot/ShimmerText";

type ChipColor =
  (typeof BROWSER_STATUS_META)[keyof typeof BROWSER_STATUS_META]["color"];

// The tab's surface color — the cove curves and the toolbar must all be
// exactly this so tab → toolbar reads as one continuous piece of chrome.
const TAB_SURFACE = "#27272a"; // zinc-800

// Long enough to read the final status, short enough not to feel stuck open.
const PANEL_CLOSE_DELAY_MS = 2500;

function hostnameOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

/** Strip the scheme + trailing slash the way Chrome's omnibox displays URLs. */
function displayUrl(url: string | null): string {
  if (!url) return "about:blank";
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

/**
 * The smooth "lip" where the tab meets the toolbar: an inverted-radius curve
 * on each side, drawn as a small SVG in the tab's own color.
 */
function TabCove({ side }: { side: "left" | "right" }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className={`absolute bottom-0 size-4 ${
        side === "left" ? "-left-4" : "-right-4 -scale-x-100"
      }`}
    >
      <path d="M16 0 Q16 16 0 16 L16 16 Z" fill={TAB_SURFACE} />
    </svg>
  );
}

/**
 * The live browser as a browser: a Chrome-style surface in the right side
 * panel — a tab carrying the page's favicon and title, an omnibox, the live
 * screen, and an action bar directly under the screen that carries the
 * takeover ask during a handoff. Renders purely from the browser-panel store,
 * which the chat's browser card keeps in sync from the SSE stream.
 */
export function BrowserLivePanel() {
  const {
    cardId,
    sessionId,
    liveViewUrl,
    status,
    currentTask,
    pendingHandoff,
    close,
  } = useBrowserPanel();

  // A finished run has nothing left to watch (the socket is gone, the card has
  // the recap), so hand the width back to the conversation — after a beat, so
  // the final frame and status are seen rather than vanishing on completion.
  const finished =
    status === "completed" || status === "failed" || status === "cancelled";
  useEffect(() => {
    if (!finished) return undefined;
    const timer = setTimeout(() => {
      close();
    }, PANEL_CLOSE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [finished, close]);

  if (!cardId) return null;

  return (
    <BrowserChrome
      key={cardId}
      sessionId={finished ? null : sessionId}
      liveViewUrl={liveViewUrl}
      status={status}
      currentTask={currentTask}
      pendingHandoff={pendingHandoff}
      onClose={close}
    />
  );
}

function TabStrip({
  title,
  host,
  favicon,
  statusMeta,
  working,
  onClose,
}: {
  title: string | null;
  host: string | null;
  favicon: string | null;
  statusMeta: { label: string; color: ChipColor } | null;
  working: boolean;
  onClose: () => void;
}) {
  const [faviconFailed, setFaviconFailed] = useState(false);
  return (
    <div className="flex items-end px-4 pt-2">
      <div className="relative flex h-9 min-w-0 max-w-[60%] items-center gap-2 rounded-t-[14px] bg-zinc-800 px-4">
        <TabCove side="left" />
        {(favicon || host) && !faviconFailed ? (
          <Image
            // The icon the PAGE declares (what the user's own browser tab shows).
            // The icon service is only the fallback for a page that declares none.
            src={
              favicon ??
              `https://www.google.com/s2/favicons?domain=${host}&sz=64`
            }
            alt=""
            width={14}
            height={14}
            unoptimized
            className="size-3.5 shrink-0 rounded-sm"
            onError={() => setFaviconFailed(true)}
          />
        ) : (
          <AiWebBrowsingIcon className="size-3.5 shrink-0 text-zinc-400" />
        )}
        <span className="truncate text-xs text-zinc-200">
          {title || "New tab"}
        </span>
        <TabCove side="right" />
      </div>
      <div className="ml-auto flex items-center gap-1.5 pb-1.5 pl-4">
        {working && (
          <Spinner size="sm" color="current" className="text-[#00bbff]" />
        )}
        {statusMeta && (
          <Chip
            size="sm"
            variant="flat"
            color={statusMeta.color}
            classNames={
              working
                ? { base: "!bg-[#00bbff]/15", content: "!text-[#00bbff]" }
                : undefined
            }
          >
            {statusMeta.label}
          </Chip>
        )}
        <Button
          isIconOnly
          size="sm"
          variant="light"
          radius="full"
          className="text-zinc-400"
          aria-label="Close browser panel"
          onPress={onClose}
        >
          <Cancel01Icon className="size-4" />
        </Button>
      </div>
    </div>
  );
}

type PanelStatus = ReturnType<typeof useBrowserPanel.getState>["status"];

/** The omnibox — one continuous surface with the tab. No back or reload glyphs:
 * this browser is driven by the agent, and a control that cannot act is worse
 * than no control. */
function Omnibox({
  url,
  pageUrl,
}: {
  url: string | null;
  pageUrl: string | null;
}) {
  return (
    <div className="flex items-center gap-2 bg-zinc-800 px-4 py-2">
      <div className="flex min-w-0 flex-1 items-center gap-2 rounded-full bg-zinc-900 px-3.5 py-1.5">
        {url?.startsWith("https://") && (
          <SquareLock02Icon className="size-3 shrink-0 text-zinc-500" />
        )}
        <span className="truncate text-xs text-zinc-400">
          {displayUrl(url)}
        </span>
      </div>
      {pageUrl && (
        <Tooltip content="Open in a new tab" size="sm" delay={400}>
          <Button
            as="a"
            href={pageUrl}
            target="_blank"
            rel="noopener noreferrer"
            isIconOnly
            size="sm"
            variant="light"
            radius="full"
            className="shrink-0 text-zinc-400"
            aria-label="Open the live browser in a new tab"
          >
            <SquareArrowUpRight02Icon className="size-4" />
          </Button>
        </Tooltip>
      )}
    </div>
  );
}

/** The screen at its natural height, so the action bar sits right below it. */
function LiveScreen({
  canvasRef,
  liveStatus,
  interactive,
}: {
  canvasRef: ReturnType<typeof useLiveBrowser>["canvasRef"];
  liveStatus: LiveStatus;
  interactive: boolean;
}) {
  return (
    <>
      <canvas
        ref={canvasRef}
        width={1280}
        height={800}
        tabIndex={interactive ? 0 : -1}
        className={`block h-auto w-full shrink-0 outline-none ${
          interactive ? "cursor-crosshair touch-none" : "pointer-events-none"
        }`}
      />
      {liveStatus !== "live" && (
        <div className="flex items-center gap-2 bg-zinc-800 px-4 py-3 text-xs text-zinc-400">
          {liveStatus === "connecting" && <Spinner size="sm" color="current" />}
          {liveStatus === "closed"
            ? "This browser session has ended"
            : "Connecting…"}
        </div>
      )}
    </>
  );
}

/** Directly under the screen: the takeover ask during a handoff, else the agent's current step. */
function ActionBar({
  pendingHandoff,
  currentTask,
  done,
}: {
  pendingHandoff: BrowserHandoffSnapshot | null;
  currentTask: string | null;
  done: boolean;
}) {
  if (pendingHandoff) {
    return (
      <div className="bg-zinc-800 px-4 pb-4 pt-3">
        <HandoffPrompt
          key={pendingHandoff.handoff_id}
          handoff={pendingHandoff}
          inPanel
        />
      </div>
    );
  }
  if (!currentTask || done) return null;
  return (
    <div className="bg-zinc-800 px-4 py-3 text-sm">
      <ShimmerText text={currentTask} />
    </div>
  );
}

function BrowserChrome({
  sessionId,
  liveViewUrl,
  status,
  currentTask,
  pendingHandoff,
  onClose,
}: {
  sessionId: string | null;
  liveViewUrl: string | null;
  status: PanelStatus;
  currentTask: string | null;
  pendingHandoff: BrowserHandoffSnapshot | null;
  onClose: () => void;
}) {
  const interactive = !!pendingHandoff;
  const { socketUrl, pageUrl, renew } = useLiveView(sessionId, liveViewUrl);
  const {
    canvasRef,
    status: liveStatus,
    page,
  } = useLiveBrowser(socketUrl, interactive, renew);
  const statusMeta = status ? BROWSER_STATUS_META[status] : null;
  const done =
    status === "completed" || status === "failed" || status === "cancelled";
  const working = status === "running";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-zinc-900">
      <TabStrip
        title={page.title}
        host={hostnameOf(page.url)}
        favicon={page.favicon}
        statusMeta={statusMeta}
        working={working}
        onClose={onClose}
      />
      <Omnibox url={page.url} pageUrl={pageUrl} />
      {socketUrl && !done ? (
        <LiveScreen
          canvasRef={canvasRef}
          liveStatus={liveStatus}
          interactive={interactive}
        />
      ) : (
        <div className="flex aspect-[8/5] items-center justify-center bg-zinc-800 text-sm text-zinc-500">
          {done ? "This browser session has ended." : "Connecting…"}
        </div>
      )}
      <ActionBar
        pendingHandoff={pendingHandoff}
        currentTask={currentTask}
        done={done}
      />
    </div>
  );
}
