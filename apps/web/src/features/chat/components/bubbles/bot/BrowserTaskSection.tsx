"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { AiWebBrowsingIcon, Alert01Icon, CheckmarkCircle02Icon } from "@icons";
import { useCallback, useEffect, useMemo, useRef } from "react";
import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import { BrowserStatusChip } from "@/features/browser/components/BrowserStatusChip";
import { useLiveView } from "@/features/browser/hooks/useLiveView";
import { useBrowserPanel } from "@/features/browser/stores/browserPanelStore";
import type { LiveSurface } from "@/features/browser/types";
import { browserCardPhase, foldBrowserTask } from "@/features/browser/utils";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useLayoutSidebar } from "@/stores/layoutStore";
import type {
  BrowserResultSnapshot,
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

/** Everything the card derives from its snapshots — folded once per render. */
function useBrowserTaskState(
  data: BrowserTaskSnapshot | BrowserTaskSnapshot[],
) {
  const snapshots = useMemo(
    () => (Array.isArray(data) ? data : [data]),
    [data],
  );
  const folded = useMemo(() => foldBrowserTask(snapshots), [snapshots]);
  const { cardId, session, steps, pendingHandoff, result } = folded;
  const phase = browserCardPhase(folded);
  // Only a live session has an owner — minting a live-view token after it
  // ends 403s. The ended state renders the recap instead.
  const live = useLiveView(phase.ended ? null : session?.session_id);
  return {
    cardId,
    session,
    steps,
    pendingHandoff,
    result,
    phase,
    live,
    // The latest step's goal, surfaced live on the collapsed steps header.
    currentTask: phase.working ? steps[steps.length - 1]?.goal : undefined,
  };
}

/** The side-panel seam: which surface shows this card's live browser, opening
 * the panel on demand or on a handoff. */
function useBrowserSidePanel({
  cardId,
  pendingHandoff,
}: Pick<ReturnType<typeof useBrowserTaskState>, "cardId" | "pendingHandoff">) {
  const isMobile = useIsMobile();
  const { setOpen: setLeftSidebarOpen } = useLayoutSidebar();
  const panelCardId = useBrowserPanel((state) => state.cardId);
  const openPanelStore = useBrowserPanel((state) => state.open);
  const closePanel = useBrowserPanel((state) => state.close);
  const inPanel = !!cardId && panelCardId === cardId;

  const openPanel = useCallback(() => {
    if (!cardId) return;
    openPanelStore(cardId);
    // The panel takes real estate from the chat column — collapse the app
    // sidebar so the conversation keeps a readable width beside the browser.
    setLeftSidebarOpen(false);
  }, [cardId, openPanelStore, setLeftSidebarOpen]);

  // A handoff is the moment the user must act in the live browser — surface the
  // panel once per handoff (desktop only; mobile keeps the in-card flow).
  const autoOpenedHandoffRef = useRef<string | null>(null);
  useEffect(() => {
    if (!pendingHandoff || isMobile) return;
    if (autoOpenedHandoffRef.current === pendingHandoff.handoff_id) return;
    autoOpenedHandoffRef.current = pendingHandoff.handoff_id;
    openPanel();
  }, [pendingHandoff, isMobile, openPanel]);

  const surface: LiveSurface = inPanel
    ? { kind: "panel" }
    : isMobile
      ? { kind: "mobile" }
      : { kind: "card", openPanel };
  return { surface, closePanel };
}

function StepsAccordion({
  steps,
  currentTask,
}: {
  steps: BrowserStepSnapshot[];
  currentTask: string | undefined;
}) {
  return (
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
  );
}

function ResultFooter({ result }: { result: BrowserResultSnapshot }) {
  return (
    <>
      <Divider className="my-3 bg-zinc-700/50" />
      <div className="flex items-start gap-2.5">
        {result.success ? (
          <CheckmarkCircle02Icon className="mt-px size-4 shrink-0 text-emerald-400" />
        ) : (
          <Alert01Icon className="mt-px size-4 shrink-0 text-zinc-500" />
        )}
        {/* The runner's summary is written for the agent and the assistant
            already retells it in its own reply — the card only reports the outcome. */}
        <p className="text-sm leading-snug text-zinc-200">
          {result.success ? "Complete" : "Didn't finish"}
        </p>
      </div>
    </>
  );
}

export default function BrowserTaskSection({ data }: BrowserTaskSectionProps) {
  const task = useBrowserTaskState(data);
  const { session, steps, pendingHandoff, result, phase, live } = task;
  const { surface, closePanel } = useBrowserSidePanel(task);

  return (
    <div className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      {/* While this card owns the side panel, mount the live browser into the
          layout's right-sidebar slot; closing the chrome releases the session. */}
      {surface.kind === "panel" && (
        <RightSidebarPanel mode="artifact" onClose={closePanel}>
          <BrowserLivePanel
            sessionId={session?.session_id ?? null}
            phase={phase}
            currentTask={task.currentTask ?? null}
            pendingHandoff={pendingHandoff ?? null}
            onClose={closePanel}
          />
        </RightSidebarPanel>
      )}
      <div className="flex items-center gap-2">
        <AiWebBrowsingIcon className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold text-zinc-100">Browser</span>
        <div className="ml-auto">
          <BrowserStatusChip phase={phase} />
        </div>
      </div>

      {session?.task && (
        <p className="mt-1 line-clamp-1 text-[13px] leading-snug text-zinc-500">
          {session.task}
        </p>
      )}

      <div className="mt-3 space-y-3">
        {phase.working && live.socketUrl && live.pageUrl && (
          <LivePreview
            socketUrl={live.socketUrl}
            pageUrl={live.pageUrl}
            currentTask={task.currentTask}
            onDropped={live.renew}
            surface={surface}
          />
        )}

        {result && <RecapViewer steps={steps} />}

        {steps.length > 0 && (
          <StepsAccordion steps={steps} currentTask={task.currentTask} />
        )}

        {pendingHandoff && (
          <HandoffPrompt
            key={pendingHandoff.handoff_id}
            handoff={pendingHandoff}
            surface={surface}
          />
        )}
      </div>

      {result && <ResultFooter result={result} />}
    </div>
  );
}
