"use client";

import { AnimatePresence, motion } from "framer-motion";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  CheckmarkCircle02Icon,
  Loading03Icon,
  TimeScheduleIcon,
} from "@/icons";

const DEMO_WORKFLOW = {
  title: "Daily Email Digest & Briefing",
  description:
    "Summarize unread emails every morning, create a briefing doc, and post key action items to Slack.",
  cronHumanReadable: "Every day at 9:00 AM",
  categories: ["gmail", "executor", "googledocs", "slack"],
};

type CardState = "idle" | "executing" | "completed";

interface DemoWorkflowCardProps {
  visible: boolean;
  state: CardState;
  colorScheme?: "dark" | "light";
}

export default function DemoWorkflowCard({
  visible,
  state,
  colorScheme = "dark",
}: DemoWorkflowCardProps) {
  const light = colorScheme === "light";

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="wf-card"
          initial={{ opacity: 0, y: 12, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{
            type: "spring",
            stiffness: 350,
            damping: 25,
          }}
          style={{ willChange: "transform, opacity" }}
          className={`max-w-sm rounded-3xl p-4 transition-shadow ${
            light
              ? "bg-white/70 backdrop-blur-lg outline outline-1 outline-zinc-200/60"
              : "bg-zinc-800"
          } ${
            state === "executing"
              ? "shadow-[0_0_24px_rgba(0,187,255,0.12)]"
              : ""
          }`}
        >
          {/* Icons row */}
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center -space-x-1.5">
              {DEMO_WORKFLOW.categories.slice(0, 3).map((cat, i) => (
                <div
                  key={cat}
                  className="relative flex h-7 w-7 items-center justify-center"
                  style={{
                    rotate: `${i % 2 === 0 ? 8 : -8}deg`,
                    zIndex: i,
                  }}
                >
                  {getToolCategoryIcon(cat, { width: 21, height: 21 })}
                </div>
              ))}
              {DEMO_WORKFLOW.categories.length > 3 && (
                <div className={`flex h-6 w-6 items-center justify-center rounded-lg text-[9px] ${
                  light ? "bg-zinc-200/60 text-zinc-500" : "bg-zinc-700/60 text-zinc-400"
                }`}>
                  +{DEMO_WORKFLOW.categories.length - 3}
                </div>
              )}
            </div>

            {/* Status */}
            <AnimatePresence mode="wait">
              {state === "executing" && (
                <motion.div
                  key="exec"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="flex items-center gap-1 rounded-full bg-primary/15 px-2 py-0.5"
                >
                  <Loading03Icon
                    width={10}
                    height={10}
                    className="animate-spin text-primary"
                  />
                  <span className="text-[9px] font-medium text-primary">
                    Running
                  </span>
                </motion.div>
              )}
              {state === "completed" && (
                <motion.div
                  key="done"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="flex items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5"
                >
                  <CheckmarkCircle02Icon
                    width={10}
                    height={10}
                    className="text-green-400"
                  />
                  <span className="text-[9px] font-medium text-green-400">
                    Completed
                  </span>
                </motion.div>
              )}
              {state === "idle" && (
                <motion.div
                  key="active"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                  <span className="text-[9px] font-medium text-green-400">
                    Active
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Title */}
          <h4 className={`text-sm font-medium ${light ? "text-zinc-800" : "text-zinc-100"}`}>
            {DEMO_WORKFLOW.title}
          </h4>
          <p className={`mt-0.5 line-clamp-1 text-[10px] ${light ? "text-zinc-500" : "text-zinc-500"}`}>
            {DEMO_WORKFLOW.description}
          </p>

          {/* Trigger + execution count */}
          <div className="mt-3 flex items-center justify-between">
            <div className={`flex items-center gap-1.5 text-[10px] ${light ? "text-zinc-500" : "text-zinc-400"}`}>
              <TimeScheduleIcon width={12} height={12} />
              <span>{DEMO_WORKFLOW.cronHumanReadable}</span>
            </div>
            {state === "completed" && (
              <span className={`text-[9px] ${light ? "text-zinc-500" : "text-zinc-600"}`}>Ran for 4s</span>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
