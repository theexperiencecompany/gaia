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
import { useHandoffDecision } from "@/features/browser/hooks/useHandoffDecision";
import { useLiveBrowser } from "@/features/browser/hooks/useLiveBrowser";
import { useBrowserPanel } from "@/features/browser/stores/browserPanelStore";
import { BROWSER_STATUS_META } from "@/features/browser/utils";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { AgentCursor } from "../bubbles/bot/AgentCursor";
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
    sessionId,
    socketUrl,
    pageUrl,
    status,
    currentTask,
    pendingHandoff,
    agentCursor,
    close,
  } = useBrowserPanel();
  const closeSidebar = useRightSidebar((state) => state.close);
  const sidebarOpen = useRightSidebar((state) => state.isOpen);

  // The sidebar chrome (Escape, other panels taking over) can close the panel
  // without our close button — release the session either way so the card's
  // inline preview resumes.
  useEffect(() => {
    if (!sidebarOpen) close();
  }, [sidebarOpen, close]);

  // A finished run has nothing left to watch: the live socket is gone and the
  // card below carries the recap. Hand the width back to the conversation
  // instead of leaving a dead browser pinned open. Delayed a beat so the final
  // frame and status are visible rather than vanishing on completion.
  const finished =
    status === "completed" || status === "failed" || status === "cancelled";
  useEffect(() => {
    if (!finished) return undefined;
    const timer = setTimeout(() => {
      close();
      closeSidebar();
    }, PANEL_CLOSE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [finished, close, closeSidebar]);

  if (!sessionId) return null;

  return (
    <BrowserChrome
      key={sessionId}
      socketUrl={socketUrl}
      pageUrl={pageUrl}
      status={status}
      currentTask={currentTask}
      agentCursor={agentCursor}
      pendingHandoffId={pendingHandoff?.handoff_id ?? null}
      handoffReason={pendingHandoff?.reason ?? null}
      onClose={() => {
        close();
        closeSidebar();
      }}
    />
  );
}

function TabStrip({
  title,
  host,
  statusMeta,
  working,
  onClose,
}: {
  title: string | null;
  host: string | null;
  statusMeta: { label: string; color: ChipColor } | null;
  working: boolean;
  onClose: () => void;
}) {
  const [faviconFailed, setFaviconFailed] = useState(false);
  return (
    <div className="flex items-end px-4 pt-2">
      <div className="relative flex h-9 min-w-0 max-w-[60%] items-center gap-2 rounded-t-[14px] bg-zinc-800 px-4">
        <TabCove side="left" />
        {host && !faviconFailed ? (
          <Image
            src={`https://www.google.com/s2/favicons?domain=${host}&sz=64`}
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

function BrowserChrome({
  socketUrl,
  pageUrl,
  status,
  currentTask,
  agentCursor,
  pendingHandoffId,
  handoffReason,
  onClose,
}: {
  socketUrl: string | null;
  pageUrl: string | null;
  status: ReturnType<typeof useBrowserPanel.getState>["status"];
  currentTask: string | null;
  agentCursor: ReturnType<typeof useBrowserPanel.getState>["agentCursor"];
  pendingHandoffId: string | null;
  handoffReason: string | null;
  onClose: () => void;
}) {
  const interactive = !!pendingHandoffId;
  const {
    canvasRef,
    status: liveStatus,
    page,
  } = useLiveBrowser(socketUrl, interactive);
  const statusMeta = status ? BROWSER_STATUS_META[status] : null;
  const done =
    status === "completed" || status === "failed" || status === "cancelled";
  const working = status === "running" && !pendingHandoffId;
  const host = hostnameOf(page.url);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-zinc-900">
      <TabStrip
        title={page.title}
        host={host}
        statusMeta={statusMeta}
        working={working}
        onClose={onClose}
      />

      {/* Toolbar — the omnibox, one continuous surface with the tab. No back or
          reload glyphs: this browser is driven by the agent, and a control that
          cannot act is worse than no control. */}
      <div className="flex items-center gap-2 bg-zinc-800 px-4 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-full bg-zinc-900 px-3.5 py-1.5">
          {page.url?.startsWith("https://") && (
            <SquareLock02Icon className="size-3 shrink-0 text-zinc-500" />
          )}
          <span className="truncate text-xs text-zinc-400">
            {displayUrl(page.url)}
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

      {/* The screen — natural height, so the action bar sits right below it. */}
      {socketUrl && !done ? (
        <>
          <div className="relative shrink-0">
            <canvas
              ref={canvasRef}
              width={1280}
              height={800}
              tabIndex={interactive ? 0 : -1}
              className={`block h-auto w-full outline-none ${
                interactive ? "cursor-crosshair" : "pointer-events-none"
              }`}
            />
            {!interactive && liveStatus === "live" && (
              <AgentCursor target={agentCursor} />
            )}
          </div>
          {liveStatus !== "live" && (
            <div className="flex items-center gap-2 bg-zinc-800 px-4 py-3 text-xs text-zinc-400">
              {liveStatus === "connecting" && (
                <Spinner size="sm" color="current" />
              )}
              {liveStatus === "closed"
                ? "This browser session has ended"
                : "Connecting…"}
            </div>
          )}
        </>
      ) : (
        <div className="flex aspect-[8/5] items-center justify-center bg-zinc-800 text-sm text-zinc-500">
          {done ? "This browser session has ended." : "Connecting…"}
        </div>
      )}

      {/* Action bar — directly under the screen. */}
      {pendingHandoffId && handoffReason ? (
        <HandoffBar
          key={pendingHandoffId}
          handoffId={pendingHandoffId}
          reason={handoffReason}
          onClosePanel={onClose}
        />
      ) : (
        currentTask &&
        !done && (
          <div className="bg-zinc-800 px-4 py-3 text-sm">
            <ShimmerText text={currentTask} />
          </div>
        )
      )}
    </div>
  );
}

function HandoffBar({
  handoffId,
  reason,
  onClosePanel,
}: {
  handoffId: string;
  reason: string;
  onClosePanel: () => void;
}) {
  const { decide, decided, pending, settled } = useHandoffDecision(
    handoffId,
    // A stop/timeout ends the session — nothing left to watch, so the panel
    // bows out. A continue keeps it open to watch the agent resume.
    (settledStatus) => {
      if (settledStatus !== "completed") onClosePanel();
    },
  );

  return (
    <div className="bg-zinc-800 px-4 pb-4 pt-3">
      <p className="mb-2.5 line-clamp-2 text-[13px] leading-snug text-zinc-200">
        {reason}
      </p>
      {settled ? (
        <p className="text-xs text-zinc-400">
          {settled === "completed" ? "Done, resuming the task." : "Stopped."}
        </p>
      ) : (
        // Same two choices as the chat card, same order and weight — the two
        // surfaces are one component to the user, so they must not diverge.
        <div className="flex items-center gap-2">
          <Button
            radius="sm"
            variant="flat"
            className="flex-1 font-semibold text-zinc-100"
            isLoading={pending || !!decided}
            onPress={() => decide("continue")}
          >
            I&rsquo;m done
          </Button>
          <Button
            variant="light"
            radius="sm"
            className="shrink-0 px-3 text-zinc-500"
            isDisabled={pending || !!decided}
            onPress={() => decide("cancel")}
          >
            Skip
          </Button>
        </div>
      )}
    </div>
  );
}
