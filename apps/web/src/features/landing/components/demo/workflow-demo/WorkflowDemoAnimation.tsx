"use client";

import { AnimatePresence, motion } from "framer-motion";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import DemoCommunityCards from "./DemoCommunityCards";
import DemoExecutionChat from "./DemoExecutionChat";
import DemoWorkflowCard from "./DemoWorkflowCard";
import DemoWorkflowModal from "./DemoWorkflowModal";
import {
  WORKFLOW_TIMINGS,
  wfEase,
  type WorkflowDemoPhase,
} from "./workflowDemoConstants";

export default function WorkflowDemoAnimation() {
  const [phase, setPhase] = useState<WorkflowDemoPhase>("idle");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearAll = () => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
  };

  const add = (fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  };

  const runAnimation = () => {
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
  };

  useEffect(() => {
    runAnimation();
    return () => clearAll();
  }, []);

  // Derive states for child components
  const showModal = [
    "modal_appear",
    "trigger_config",
    "schedule_set",
    "steps_generating",
  ].includes(phase);

  const showCard = [
    "card_appear",
    "execution_start",
    "tool_calls",
    "execution_response",
    "execution_complete",
  ].includes(phase);

  const cardState = ["execution_start", "tool_calls"].includes(phase)
    ? ("executing" as const)
    : ["execution_complete"].includes(phase)
      ? ("completed" as const)
      : ("idle" as const);

  const showExecChat = [
    "tool_calls",
    "execution_response",
    "execution_complete",
  ].includes(phase);

  const showCommunity = [
    "publish_button",
    "publish_click",
    "community_cards",
    "done",
  ].includes(phase);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.97 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, ease: wfEase }}
      className="relative flex h-[65vh] w-full items-center justify-center overflow-hidden rounded-2xl"
    >
      {/* Background image with subtle Ken Burns effect */}
      <motion.div
        className="absolute inset-0"
        animate={{ scale: [1, 1.1, 1] }}
        transition={{
          duration: 10,
          repeat: Number.POSITIVE_INFINITY,
          ease: "linear",
        }}
      >
        <Image
          src="/images/wallpapers/mesh_gradient_1.png"
          alt=""
          fill
          className="object-cover"
          priority
        />
      </motion.div>

      {/* Overlay for readability */}
      <div className="absolute inset-0 bg-black/10 backdrop-blur-sm" />

      {/* Animated content layer */}
      <div className="relative z-10 flex w-full flex-col items-center justify-center px-6">
        <AnimatePresence mode="wait">
          {/* Modal phase */}
          {showModal && (
            <motion.div
              key="modal"
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25, ease: wfEase }}
              style={{ willChange: "opacity" }}
            >
              <DemoWorkflowModal phase={phase} />
            </motion.div>
          )}

          {/* Card + execution phase */}
          {!showModal && showCard && (
            <motion.div
              key="execution"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: wfEase }}
              style={{ willChange: "opacity" }}
              className="flex w-full max-w-xl flex-col items-end gap-4 scale-120"
            >
              <DemoWorkflowCard visible={showCard} state={cardState} colorScheme="light" />
              {showExecChat && <DemoExecutionChat phase={phase} colorScheme="light" />}
            </motion.div>
          )}

          {/* Publish + community cards phase */}
          {showCommunity && (
            <motion.div
              key="community"
              initial={false}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: wfEase }}
              style={{ willChange: "opacity" }}
              className="w-full px-4"
            >
              <DemoCommunityCards phase={phase} colorScheme="light" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
