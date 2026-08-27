"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Spinner } from "@heroui/spinner";
import { AiWebBrowsingIcon, Alert01Icon, CheckmarkCircle02Icon } from "@icons";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  liveViewPageUrl,
  liveViewSocketUrl,
} from "@/features/browser/api/browserApi";
import { useLiveViewToken } from "@/features/browser/hooks/useLiveViewToken";
import { useBrowserPanel } from "@/features/browser/stores/browserPanelStore";
import { BROWSER_STATUS_META } from "@/features/browser/utils";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import type {
  BrowserHandoffSnapshot,
  BrowserResultSnapshot,
  BrowserSessionSnapshot,
  BrowserSessionStatus,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "@/types/features/browserTaskTypes";
import { BrowserLivePanel } from "../../browser/BrowserLivePanel";
import { HandoffPrompt } from "./HandoffPrompt";
import { LivePreview } from "./LivePreview";
import { RecapViewer } from "./RecapViewer";
import { ShimmerText } from "./ShimmerText";
import { StepRow } from "./StepRow";

interface BrowserTaskSectionProps {
  data: BrowserTaskSnapshot | BrowserTaskSnapshot[];
}

interface FoldedState {
  session?: BrowserSessionSnapshot;
  steps: BrowserStepSnapshot[];
  handoffs: BrowserHandoffSnapshot[];
  result?: BrowserResultSnapshot;
}

function fold(snapshots: BrowserTaskSnapshot[]): FoldedState {
  let session: BrowserSessionSnapshot | undefined;
  let result: BrowserResultSnapshot | undefined;
  const steps = new Map<number, BrowserStepSnapshot>();
  const handoffs = new Map<string, BrowserHandoffSnapshot>();

  for (const snap of snapshots) {
    if (snap.kind === "session") session = snap;
    else if (snap.kind === "step") steps.set(snap.index, snap);
    else if (snap.kind === "handoff")
      handoffs.set(snap.handoff_id, snap); // last wins
    else if (snap.kind === "result") result = snap;
  }

  return {
    session,
    result,
    steps: [...steps.values()].sort((a, b) => a.index - b.index),
    handoffs: [...handoffs.values()],
  };
}

export default function BrowserTaskSection({ data }: BrowserTaskSectionProps) {
  const snapshots = useMemo(
    () => (Array.isArray(data) ? data : [data]),
    [data],
  );
  const { session, steps, handoffs, result } = useMemo(
    () => fold(snapshots),
    [snapshots],
  );

  const pendingHandoff = handoffs.find((h) => h.status === "pending");
  const status: BrowserSessionStatus =
    result?.status ??
    (pendingHandoff ? "paused" : (session?.status ?? "running"));
  const statusMeta = BROWSER_STATUS_META[status];
  const active = !result;
  const working = active && !pendingHandoff;
  // Only an active session has an owner — minting a live-view token after it
  // ends 403s ("Not authorized for this session"). Fetch it while the session
  // is active (working or paused on a handoff — the side panel streams during
  // both); the done state renders the recap instead.
  const liveViewToken = useLiveViewToken(active ? session?.session_id : null);
  // What the agent is doing right now — the latest step's goal, surfaced live
  // on the (collapsed) steps header so the user sees progress without expanding.
  const currentTask = working ? steps[steps.length - 1]?.goal : undefined;

  const isMobile = useIsMobile();
  const openSidebarWithContent = useRightSidebar(
    (state) => state.openWithContent,
  );
  const panelSessionId = useBrowserPanel((state) => state.sessionId);
  const openPanelStore = useBrowserPanel((state) => state.open);
  const syncPanel = useBrowserPanel((state) => state.sync);
  const sessionId = session?.session_id ?? null;
  const inPanel = !!sessionId && panelSessionId === sessionId;

  const socketUrl =
    session?.live_view_url && liveViewToken
      ? liveViewSocketUrl(session.live_view_url, liveViewToken)
      : null;
  const pageUrl =
    session?.live_view_url && liveViewToken
      ? liveViewPageUrl(session.live_view_url, liveViewToken)
      : null;

  const openPanel = useCallback(() => {
    if (!sessionId) return;
    openPanelStore(sessionId);
    openSidebarWithContent(<BrowserLivePanel />, "artifact");
  }, [sessionId, openPanelStore, openSidebarWithContent]);

  // The card is the SSE-driven source of truth — while its session is shown in
  // the side panel, mirror everything the panel renders into the store.
  useEffect(() => {
    if (!inPanel || !sessionId) return;
    syncPanel({
      sessionId,
      socketUrl,
      pageUrl,
      status,
      currentTask: currentTask ?? null,
      pendingHandoff: pendingHandoff ?? null,
    });
  }, [
    inPanel,
    sessionId,
    socketUrl,
    pageUrl,
    status,
    currentTask,
    pendingHandoff,
    syncPanel,
  ]);

  // A handoff is the moment the user must act in the live browser — surface the
  // side panel for them once per handoff (desktop only; mobile keeps the
  // in-card flow). Closing the panel afterwards is respected.
  const autoOpenedHandoffRef = useRef<string | null>(null);
  useEffect(() => {
    if (!pendingHandoff || isMobile) return;
    if (autoOpenedHandoffRef.current === pendingHandoff.handoff_id) return;
    autoOpenedHandoffRef.current = pendingHandoff.handoff_id;
    openPanel();
  }, [pendingHandoff, isMobile, openPanel]);

  return (
    <div className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2">
        <AiWebBrowsingIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
        <div className="ml-auto flex items-center gap-1.5">
          {working && (
            <Spinner size="sm" color="current" className="text-[#00bbff]" />
          )}
          <Chip
            size="sm"
            variant="flat"
            color={statusMeta.color}
            // Browser accent is #00bbff — apply it to the live "Working" state.
            classNames={
              working
                ? { base: "!bg-[#00bbff]/15", content: "!text-[#00bbff]" }
                : undefined
            }
          >
            {statusMeta.label}
          </Chip>
        </div>
      </div>

      {session?.task && (
        <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-zinc-400">
          {session.task}
        </p>
      )}

      <div className="mt-3 space-y-3">
        {working && socketUrl && pageUrl && (
          <LivePreview
            socketUrl={socketUrl}
            pageUrl={pageUrl}
            currentTask={currentTask}
            inPanel={inPanel}
            onOpenPanel={isMobile ? undefined : openPanel}
          />
        )}

        {result && <RecapViewer steps={steps} />}

        {steps.length > 0 && (
          <Accordion isCompact className="px-0" variant="light">
            <AccordionItem
              key="steps"
              aria-label="Steps"
              title={
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 text-sm font-medium text-zinc-300">
                    Steps
                  </span>
                  <Chip
                    size="sm"
                    variant="flat"
                    classNames={{
                      base: "h-5 bg-zinc-700",
                      content: "px-1.5 text-xs text-zinc-300",
                    }}
                  >
                    {steps.length}
                  </Chip>
                  {currentTask && (
                    <span className="min-w-0 flex-1 truncate text-xs">
                      <ShimmerText text={currentTask} />
                    </span>
                  )}
                </div>
              }
              classNames={{ trigger: "py-2", content: "space-y-2 pb-2" }}
            >
              {steps.map((step) => (
                <StepRow key={`browser-step-${step.index}`} step={step} />
              ))}
            </AccordionItem>
          </Accordion>
        )}

        {pendingHandoff && (
          <HandoffPrompt
            key={pendingHandoff.handoff_id}
            handoff={pendingHandoff}
            inPanel={inPanel}
            onOpenPanel={isMobile ? undefined : openPanel}
          />
        )}
      </div>

      {result && (
        <>
          <Divider className="my-3 bg-zinc-700/50" />
          <div className="flex items-start gap-2.5">
            {result.success ? (
              <CheckmarkCircle02Icon className="mt-px size-4 shrink-0 text-emerald-400" />
            ) : (
              <Alert01Icon className="mt-px size-4 shrink-0 text-zinc-500" />
            )}
            {/* The runner's summary is written for the agent ("I have searched
                for 'mechanical keyboard'…") and the assistant already retells it
                in its own reply — in the card it is redundant noise, so this
                line only reports the outcome. */}
            <p className="text-sm leading-snug text-zinc-200">
              {result.success ? "Complete" : "Didn't finish"}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
