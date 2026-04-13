"use client";

import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";

// ─── Constants ─────────────────────────────────────────────────────────────────

const SCREEN_INTERVAL_MS = 2500;
const SCREEN_COUNT = 4;

const TODO_ITEMS = [
  { id: "t1", label: "Review sprint backlog", done: true },
  { id: "t2", label: "Send weekly update email", done: false },
  { id: "t3", label: "Finalize Q2 roadmap", done: false },
];

// ─── Screen Components ─────────────────────────────────────────────────────────

function ChatScreen() {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-8 pb-2 border-b border-zinc-800">
        <p className="text-xs font-semibold text-zinc-100 text-center">GAIA</p>
        <p className="text-[10px] text-zinc-500 text-center">AI Assistant</p>
      </div>
      {/* Messages */}
      <div className="flex flex-col gap-2 px-3 pt-3 flex-1">
        {/* User bubble */}
        <div className="flex justify-end">
          <span className="text-[10px] bg-[#00bbff]/20 text-[#00bbff] rounded-xl px-2 py-1.5 max-w-[75%]">
            What should I focus on today?
          </span>
        </div>
        {/* GAIA reply */}
        <div className="flex justify-start">
          <span className="text-[10px] bg-zinc-800 text-zinc-300 rounded-xl px-2 py-1.5 max-w-[80%]">
            3 tasks due, 1 meeting at 3pm. I&apos;d start with the sprint
            backlog review.
          </span>
        </div>
      </div>
    </div>
  );
}

function TodosScreen() {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-8 pb-2 border-b border-zinc-800">
        <p className="text-xs font-semibold text-zinc-100 text-center">
          Tasks · Today
        </p>
      </div>
      {/* Todo list */}
      <div className="flex flex-col gap-2 px-3 pt-3">
        {TODO_ITEMS.map((item) => (
          <div key={item.id} className="flex items-center gap-2">
            {/* Checkbox */}
            <div
              className={`w-3.5 h-3.5 rounded-full border shrink-0 flex items-center justify-center ${
                item.done
                  ? "bg-[#00bbff] border-[#00bbff]"
                  : "border-zinc-600 bg-transparent"
              }`}
            >
              {item.done && (
                <svg
                  width="8"
                  height="6"
                  viewBox="0 0 8 6"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M1 3L3 5L7 1"
                    stroke="black"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </div>
            <span
              className={`text-[10px] ${item.done ? "line-through text-zinc-500" : "text-zinc-300"}`}
            >
              {item.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WorkflowScreen() {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-8 pb-2 border-b border-zinc-800">
        <p className="text-xs font-semibold text-zinc-100 text-center">
          Workflows
        </p>
      </div>
      {/* Running workflow */}
      <div className="px-3 pt-4">
        <div className="rounded-xl bg-zinc-800 p-3">
          <div className="flex items-center gap-2">
            {/* Spinning indicator */}
            <m.div
              className="w-3 h-3 rounded-full border-2 border-[#00bbff] border-t-transparent shrink-0"
              animate={{ rotate: 360 }}
              transition={{
                duration: 0.8,
                repeat: Number.POSITIVE_INFINITY,
                ease: "linear",
              }}
            />
            <p className="text-[10px] font-medium text-zinc-200">
              Daily Digest · Running...
            </p>
          </div>
          <p className="text-[10px] text-zinc-500 mt-1.5 ml-5">
            Completed today: 3
          </p>
        </div>
      </div>
    </div>
  );
}

function NotificationScreen() {
  return (
    <div className="flex flex-col h-full bg-zinc-950/80">
      {/* Notification card */}
      <div className="px-3 pt-10">
        <div className="rounded-2xl bg-zinc-800 p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <div className="w-4 h-4 rounded-full bg-[#00bbff]/20 flex items-center justify-center">
              <div className="w-2 h-2 rounded-full bg-[#00bbff]" />
            </div>
            <span className="text-[9px] font-semibold text-zinc-300">
              GAIA · Daily Briefing Ready
            </span>
          </div>
          <p className="text-[9px] text-zinc-500 leading-relaxed">
            Your 8am summary is ready — 3 tasks due, 2 emails to review, and
            weather looks clear.
          </p>
        </div>
      </div>
    </div>
  );
}

const SCREENS = [
  { id: "chat", component: <ChatScreen /> },
  { id: "todos", component: <TodosScreen /> },
  { id: "workflow", component: <WorkflowScreen /> },
  { id: "notification", component: <NotificationScreen /> },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function MobileDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: false, margin: "-50px" });
  const [currentScreen, setCurrentScreen] = useState(0);

  useEffect(() => {
    if (!isInView) return;
    const id = setInterval(() => {
      setCurrentScreen((prev) => (prev + 1) % SCREEN_COUNT);
    }, SCREEN_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isInView]);

  return (
    <div
      ref={ref}
      className="w-full flex flex-col items-center gap-4 select-none"
    >
      {/* Phone frame */}
      <div className="w-48 mx-auto relative rounded-[2.5rem] bg-zinc-800 p-2 shadow-2xl">
        {/* Inner screen */}
        <div className="rounded-[2rem] bg-zinc-900 overflow-hidden h-80 relative">
          {/* Notch */}
          <div className="absolute top-2 left-1/2 -translate-x-1/2 w-10 h-3 bg-black rounded-full z-10" />

          {/* Screens */}
          <AnimatePresence mode="wait">
            <m.div
              key={currentScreen}
              className="absolute inset-0"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
            >
              {SCREENS[currentScreen].component}
            </m.div>
          </AnimatePresence>
        </div>
      </div>

      {/* Dot indicators */}
      <div className="flex items-center gap-1.5">
        {SCREENS.map((screen, i) => (
          <m.div
            key={screen.id}
            className="h-1.5 rounded-full bg-zinc-600"
            animate={{
              width: i === currentScreen ? 16 : 6,
              backgroundColor:
                i === currentScreen ? "#00bbff" : "rgb(82 82 91)",
            }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
          />
        ))}
      </div>
    </div>
  );
}
