"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, RedoIcon } from "@icons";
import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import DummyComposer from "@/features/landing/components/demo/DummyComposer";
import DemoCommunityCards from "./DemoCommunityCards";
import DemoExecutionChat from "./DemoExecutionChat";

import DemoWorkflowCard from "./DemoWorkflowCard";
import DemoWorkflowModal from "./DemoWorkflowModal";
import {
  WORKFLOW_TIMINGS,
  type WorkflowDemoPhase,
  wfEase,
} from "./workflowDemoConstants";

const PHASE_ORDER: WorkflowDemoPhase[] = [
  "idle",
  "modal_appear",
  "trigger_config",
  "schedule_set",
  "steps_generating",
  "modal_close",
  "card_appear",
  "execution_start",
  "tool_calls",
  "execution_response",
  "execution_complete",
  "publish_button",
  "publish_click",
  "community_cards",
  "done",
];

const MemoDemoWorkflowModal = memo(DemoWorkflowModal);
const _MemoDemoWorkflowCard = memo(DemoWorkflowCard);
const MemoDemoExecutionChat = memo(DemoExecutionChat);
const MemoDemoCommunityCards = memo(DemoCommunityCards);
const MemoDummyComposer = memo(DummyComposer);

const WorkflowBackground = memo(function WorkflowBackground() {
  return (
    <Image
      src="/images/wallpapers/mesh_gradient_1.webp"
      alt="Mesh gradient background"
      width={1920}
      height={1080}
      sizes="100vw"
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        position: "absolute",
        inset: 0,
      }}
      className="object-cover"
      priority
    />
  );
});

export default function WorkflowDemoAnimation() {
  const [phase, setPhase] = useState<WorkflowDemoPhase>("idle");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const hasStarted = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, amount: 0.3 });

  const clearAll = useCallback(() => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
  }, []);

  const add = useCallback((fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  }, []);

  const runAnimation = useCallback(() => {
    const T = WORKFLOW_TIMINGS;
    clearAll();
    setPhase("idle");

    add(() => setPhase("modal_appear"), T.modalAppear);
    add(() => setPhase("trigger_config"), T.triggerConfig);
    add(() => setPhase("schedule_set"), T.scheduleSet);
    add(() => setPhase("steps_generating"), T.stepsGenerating);
    add(() => setPhase("modal_close"), T.modalClose);
    add(() => setPhase("card_appear"), T.cardAppear);
    add(() => setPhase("execution_start"), T.executionStart);
    add(() => setPhase("tool_calls"), T.toolCalls);
    add(() => setPhase("execution_response"), T.executionResponse);
    add(() => setPhase("execution_complete"), T.executionComplete);
    add(() => setPhase("publish_button"), T.publishButton);
    add(() => setPhase("publish_click"), T.publishClick);
    add(() => setPhase("community_cards"), T.communityCards);
    add(() => setPhase("done"), T.done);

    // Loop
    add(() => runAnimation(), T.loop);
  }, [add, clearAll]);

  const goToPhase = useCallback(
    (targetPhase: WorkflowDemoPhase) => {
      clearAll();
      setPhase(targetPhase);
    },
    [clearAll],
  );

  const prevPhase = useCallback(() => {
    const idx = PHASE_ORDER.indexOf(phase);
    if (idx > 0) goToPhase(PHASE_ORDER[idx - 1]);
  }, [phase, goToPhase]);

  const nextPhase = useCallback(() => {
    const idx = PHASE_ORDER.indexOf(phase);
    if (idx < PHASE_ORDER.length - 1) goToPhase(PHASE_ORDER[idx + 1]);
  }, [phase, goToPhase]);

  useEffect(() => {
    if (isInView && !hasStarted.current) {
      hasStarted.current = true;
      runAnimation();
    }
    return () => clearAll();
  }, [clearAll, isInView, runAnimation]);

  // Derive states for child components
  const showModal = useMemo(
    () =>
      [
        "modal_appear",
        "trigger_config",
        "schedule_set",
        "steps_generating",
      ].includes(phase),
    [phase],
  );

  const showCard = useMemo(
    () =>
      [
        "card_appear",
        "execution_start",
        "tool_calls",
        "execution_response",
        "execution_complete",
      ].includes(phase),
    [phase],
  );

  const cardState = useMemo(() => {
    if (["execution_start", "tool_calls"].includes(phase)) {
      return "executing" as const;
    }
    if (["execution_complete"].includes(phase)) {
      return "completed" as const;
    }
    return "idle" as const;
  }, [phase]);

  const showExecChat = useMemo(
    () =>
      ["tool_calls", "execution_response", "execution_complete"].includes(
        phase,
      ),
    [phase],
  );

  const showCommunity = useMemo(
    () =>
      ["publish_button", "publish_click", "community_cards", "done"].includes(
        phase,
      ),
    [phase],
  );

  // Show composer during execution phases
  const showComposer = showCard;

  const handleRestart = useCallback(() => {
    runAnimation();
  }, [runAnimation]);

  return (
    <div ref={containerRef} className="flex flex-col items-center gap-4">
      <m.div
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        whileInView={{ opacity: 1, y: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, ease: wfEase }}
        className="relative flex h-[70vh] w-full items-center justify-center overflow-hidden rounded-2xl"
      >
        {/* Background image with subtle Ken Burns effect */}
        <m.div
          className="absolute inset-0"
          animate={{ scale: [1, 1.1, 1] }}
          transition={{
            duration: 10,
            repeat: Number.POSITIVE_INFINITY,
            ease: "linear",
          }}
        >
          <WorkflowBackground />
        </m.div>

        {/* Overlay for readability */}
        <div className="absolute inset-0 bg-black/10 backdrop-blur-sm" />

        {/* Animated content layer */}
        <div className="relative z-10 flex h-full w-full flex-col items-center justify-center px-6">
          <AnimatePresence mode="wait">
            {/* Modal phase */}
            {showModal && (
              <m.div
                key="modal"
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25, ease: wfEase }}
                style={{ willChange: "opacity" }}
              >
                <MemoDemoWorkflowModal phase={phase} />
              </m.div>
            )}

            {/* Card + execution phase — chat-screen layout */}
            {!showModal && showCard && (
              <m.div
                key="execution"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3, ease: wfEase }}
                style={{ backgroundColor: "#111111" }}
                className="mx-auto flex h-[calc(75%)] w-full max-w-xl flex-col rounded-3xl my-4 scale-120"
              >
                {/* Scrollable messages area */}
                <div className="flex flex-1 flex-col items-end justify-end gap-4 overflow-y-auto p-5">
                  <DemoWorkflowCard
                    visible={showCard}
                    state={cardState}
                    colorScheme="dark"
                  />
                  {showExecChat && (
                    <MemoDemoExecutionChat phase={phase} colorScheme="dark" />
                  )}
                </div>

                {/* Fixed composer at bottom */}
                {showComposer && (
                  <div className="shrink-0 px-3 pb-3">
                    <MemoDummyComposer hideIntegrationBanner fullWidth />
                  </div>
                )}
              </m.div>
            )}

            {/* Publish + community cards phase */}
            {showCommunity && (
              <m.div
                key="community"
                initial={false}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2, ease: wfEase }}
                className="w-full px-4"
              >
                <MemoDemoCommunityCards phase={phase} colorScheme="dark" />
              </m.div>
            )}
          </AnimatePresence>
        </div>
      </m.div>

      {/* Navigation controls — below the demo container */}
      <div className="flex items-center justify-between w-full">
        <div className="flex items-center gap-1.5">
          <Button
            isIconOnly
            variant="flat"
            size="sm"
            aria-label="Previous phase"
            title="Previous phase"
            onPress={prevPhase}
            isDisabled={PHASE_ORDER.indexOf(phase) <= 0}
            className="rounded-full"
          >
            <ArrowRight02Icon width={18} height={18} className="rotate-180" />
          </Button>
          <Button
            isIconOnly
            variant="flat"
            size="sm"
            aria-label="Next phase"
            title="Next phase"
            onPress={nextPhase}
            isDisabled={PHASE_ORDER.indexOf(phase) >= PHASE_ORDER.length - 1}
            className="rounded-full"
          >
            <ArrowRight02Icon width={18} height={18} />
          </Button>
        </div>
        <Button
          isIconOnly
          variant="flat"
          size="sm"
          aria-label="Restart demo"
          title="Restart demo"
          onPress={handleRestart}
          className="rounded-full"
        >
          <RedoIcon width={18} height={18} />
        </Button>
      </div>
    </div>
  );
}
