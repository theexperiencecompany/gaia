"use client";

import { AnimatePresence, m } from "motion/react";
import Image from "next/image";
import { useEffect, useState } from "react";

import DemoToolCalls from "@/features/landing/components/demo/DemoToolCalls";
import MiniWaveSpinner from "@/features/landing/components/demo/MiniWaveSpinner";
import {
  DEMO_WORKFLOW,
  type WorkflowDemoPhase,
  wfTx,
} from "./workflowDemoConstants";

const TOOLS = DEMO_WORKFLOW.tools;
const EXECUTION_RESPONSE = DEMO_WORKFLOW.executionResponse;

interface DemoExecutionChatProps {
  phase: WorkflowDemoPhase;
  colorScheme?: "dark" | "light";
}

export default function DemoExecutionChat({
  phase,
  colorScheme = "dark",
}: DemoExecutionChatProps) {
  const light = colorScheme === "light";
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [typedResponse, setTypedResponse] = useState("");
  const [visibleToolCount, setVisibleToolCount] = useState(0);

  const showTools = [
    "tool_calls",
    "execution_response",
    "execution_complete",
    "done",
  ].includes(phase);

  const showResponse = [
    "execution_response",
    "execution_complete",
    "done",
  ].includes(phase);

  const isTyping = phase === "execution_response";

  // Stagger tool calls one by one
  useEffect(() => {
    if (phase === "tool_calls") {
      setVisibleToolCount(0);
      setToolsExpanded(true); // Start expanded immediately
      const staggerTimers: ReturnType<typeof setTimeout>[] = [];
      TOOLS.forEach((_, i) => {
        staggerTimers.push(
          setTimeout(() => setVisibleToolCount(i + 1), (i + 1) * 500),
        );
      });
      return () => staggerTimers.forEach(clearTimeout);
    }
  }, [phase]);

  // Typing effect for response
  useEffect(() => {
    if (phase === "execution_response") {
      let i = 0;
      setTypedResponse("");
      const tick = setInterval(() => {
        i += 3;
        setTypedResponse(EXECUTION_RESPONSE.slice(0, i));
        if (i >= EXECUTION_RESPONSE.length) {
          clearInterval(tick);
          setTypedResponse(EXECUTION_RESPONSE);
        }
      }, 18);
      return () => clearInterval(tick);
    }
  }, [phase]);

  // Reset between cycles
  useEffect(() => {
    if (phase === "idle") {
      setToolsExpanded(false);
      setTypedResponse("");
      setVisibleToolCount(0);
    }
  }, [phase]);

  const showSection = showTools || showResponse;

  return (
    <AnimatePresence>
      {showSection && (
        <m.div
          key="exec-chat"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={wfTx}
          className="w-full"
        >
          {/* Tool calls */}
          {showTools && (
            <div className="mb-2">
              <DemoToolCalls
                tools={TOOLS.slice(0, visibleToolCount)}
                expanded={toolsExpanded}
                onToggle={() => setToolsExpanded((e) => !e)}
                colorScheme={colorScheme}
              />
            </div>
          )}

          {/* Loading state - wave spinner + shimmering text (NO logo) */}
          <AnimatePresence>
            {(phase === "tool_calls" ||
              (showResponse && typedResponse === "")) && (
              <m.div
                key="loading-spinner"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={wfTx}
                className="flex items-center gap-2 pl-1"
              >
                <MiniWaveSpinner />
                <span
                  className={`animate-pulse text-sm ${light ? "text-zinc-500" : "text-zinc-300"}`}
                >
                  GAIA is working…
                </span>
              </m.div>
            )}
          </AnimatePresence>

          {/* Bot response bubble - only show when typing has started */}
          <AnimatePresence>
            {showResponse && typedResponse !== "" && (
              <m.div
                key="bot-response"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={wfTx}
                className="flex items-end gap-2"
              >
                <Image
                  src="/images/logos/logo.webp"
                  width={28}
                  height={28}
                  loading="lazy"
                  alt="GAIA"
                  className="shrink-0 z-3"
                />
                <div
                  className={`imessage-bubble imessage-from-them text-sm leading-relaxed ${
                    light ? "text-zinc-800" : "text-white"
                  }`}
                  style={{
                    ...(light
                      ? {
                          background: "rgba(255, 255, 255, 0.85)",
                          backdropFilter: "blur(8px)",
                        }
                      : {}),
                  }}
                >
                  {typedResponse}
                  {isTyping && (
                    <span
                      className={`ml-0.5 inline-block h-3 w-0.5 animate-pulse align-middle ${
                        light ? "bg-zinc-800/60" : "bg-white/60"
                      }`}
                    />
                  )}
                </div>
              </m.div>
            )}
          </AnimatePresence>
        </m.div>
      )}
    </AnimatePresence>
  );
}
