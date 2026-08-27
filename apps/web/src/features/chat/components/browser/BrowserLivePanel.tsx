"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { AiWebBrowsingIcon, Cancel01Icon } from "@icons";
import { useEffect } from "react";
import { useBrowserPanel } from "@/features/browser/stores/browserPanelStore";
import { BROWSER_STATUS_META } from "@/features/browser/utils";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { HandoffPrompt } from "../bubbles/bot/HandoffPrompt";
import { LiveBrowserCanvas } from "../bubbles/bot/LiveBrowserCanvas";
import { ShimmerText } from "../bubbles/bot/ShimmerText";

/**
 * The live browser in a wide split-view panel (right-sidebar "artifact"
 * variant): chat shrinks to a narrow column, the browser gets real estate.
 * Renders purely from the browser-panel store, which the chat's browser card
 * keeps in sync from the SSE stream — closing the panel hands the live view
 * back to the card's inline preview.
 */
export function BrowserLivePanel() {
  const { sessionId, socketUrl, status, currentTask, pendingHandoff, close } =
    useBrowserPanel();
  const closeSidebar = useRightSidebar((state) => state.close);
  const sidebarOpen = useRightSidebar((state) => state.isOpen);

  // The sidebar chrome (Escape, other panels taking over) can close the panel
  // without going through our close button — release the session either way so
  // the card's inline preview resumes.
  useEffect(() => {
    if (!sidebarOpen) close();
  }, [sidebarOpen, close]);

  if (!sessionId) return null;

  const statusMeta = status ? BROWSER_STATUS_META[status] : null;
  const done =
    status === "completed" || status === "failed" || status === "cancelled";
  const working = status === "running" && !pendingHandoff;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 px-4 pt-3 pb-2">
        <AiWebBrowsingIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
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
          className="ml-auto text-zinc-400"
          aria-label="Close browser panel"
          onPress={() => {
            close();
            closeSidebar();
          }}
        >
          <Cancel01Icon className="size-4" />
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 pt-1">
        {socketUrl && !done ? (
          <LiveBrowserCanvas
            key={socketUrl}
            socketUrl={socketUrl}
            interactive={!!pendingHandoff}
          />
        ) : (
          <div className="flex aspect-video items-center justify-center rounded-xl bg-zinc-950 text-sm text-zinc-500 ring-1 ring-white/10">
            {done ? "This browser session has ended." : "Connecting…"}
          </div>
        )}

        {pendingHandoff ? (
          <HandoffPrompt
            key={pendingHandoff.handoff_id}
            handoff={pendingHandoff}
            inPanel
          />
        ) : (
          currentTask &&
          !done && (
            <div className="rounded-2xl bg-zinc-900 px-4 py-3 text-sm">
              <ShimmerText text={currentTask} />
            </div>
          )
        )}
      </div>
    </div>
  );
}
