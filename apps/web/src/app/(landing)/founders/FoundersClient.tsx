"use client";

import { AnimatePresence, m, useInView } from "motion/react";
import Image from "next/image";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import DemoToolCalls from "@/features/landing/components/demo/DemoToolCalls";
import { FOUNDER_EMAIL } from "@/features/landing/components/demo/demoConstants";
import MiniWaveSpinner from "@/features/landing/components/demo/MiniWaveSpinner";
import { SimpleChatBubbleBot } from "@/features/landing/components/demo/SimpleChatBubbles";
import type { ToolStep } from "@/features/landing/components/demo/types";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";

const ease = [0.22, 1, 0.36, 1] as const;

// ─── Section Header ───────────────────────────────────────────────────

function SectionHeader({
  label,
  headline,
  description,
}: {
  label: string;
  headline: string;
  description: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.15 });

  return (
    <div ref={ref} className="flex flex-col items-center text-center">
      <m.span
        initial={{ opacity: 0, y: 8 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.5, ease }}
        className="mb-4 text-xs font-medium uppercase tracking-widest text-primary"
      >
        {label}
      </m.span>
      <m.h2
        initial={{ opacity: 0, y: 16 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease, delay: 0.08 }}
        className="font-serif mb-5 max-w-2xl text-4xl font-normal text-white sm:text-5xl"
      >
        {headline}
      </m.h2>
      <m.p
        initial={{ opacity: 0, y: 16 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease, delay: 0.16 }}
        className="mb-14 max-w-xl text-lg font-light leading-relaxed text-zinc-400"
      >
        {description}
      </m.p>
    </div>
  );
}

// ─── Chat Bubble Components ───────────────────────────────────────────

/**
 * User bubble using the real iMessage CSS classes from globals.css.
 * Uses a generic default avatar (no auth context needed on landing).
 */
function LandingUserBubble({ content }: { content: string }) {
  return (
    <div className="mb-3 flex items-end justify-end gap-3">
      <div className="chat_bubble user select-none text-sm">{content}</div>
      <div className="h-8 w-8 shrink-0 overflow-hidden rounded-full border-2 border-white/10">
        <Image
          src="/images/avatars/default.webp"
          width={32}
          height={32}
          alt="User"
          className="h-full w-full object-cover"
        />
      </div>
    </div>
  );
}

/**
 * Wrapper that pairs the GAIA avatar with DemoToolCalls.
 * Mirrors the SimpleChatBubbleBot avatar layout.
 */
function ToolCallWrapper({
  msgId,
  tools,
  expandedIds,
  onToggle,
}: {
  msgId: string;
  tools: ToolStep[];
  expandedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="relative mb-3 flex items-start gap-3">
      <div className="relative z-[1] w-[35px] shrink-0">
        <Image
          src="/images/logos/logo.webp"
          width={35}
          height={35}
          alt="GAIA"
          className="rounded-full"
        />
      </div>
      <div className="pt-1">
        <DemoToolCalls
          tools={tools}
          expanded={expandedIds.has(msgId)}
          onToggle={() => onToggle(msgId)}
        />
      </div>
    </div>
  );
}

// ─── Chat Message Type ────────────────────────────────────────────────

type MessageRole = "user" | "assistant" | "thinking" | "tools" | "card";

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  tools?: ToolStep[];
  cardContent?: ReactNode;
  delay?: number;
}

// ─── Animated Chat Demo ───────────────────────────────────────────────

/**
 * Container override for --color-primary-bg so iMessage tail
 * cut-outs match the bg-zinc-900 (#18181b) card background.
 */
const CHAT_CONTAINER_STYLE = {
  "--color-primary-bg": "#18181b",
} as React.CSSProperties;

function ChatDemo({
  messages,
  minHeight = 220,
}: {
  messages: ChatMessage[];
  minHeight?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.25 });
  const [visibleCount, setVisibleCount] = useState(0);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    let cumDelay = 400;
    messages.forEach((msg, i) => {
      const d = msg.delay ?? (msg.role === "tools" ? 350 : 750);
      cumDelay += d;
      timersRef.current.push(
        setTimeout(() => setVisibleCount(i + 1), cumDelay),
      );
    });

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView, messages]);

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div
      ref={ref}
      className="rounded-3xl bg-zinc-900 p-5 text-left"
      style={{ ...CHAT_CONTAINER_STYLE, minHeight }}
    >
      <div className="space-y-1">
        {messages.slice(0, visibleCount).map((msg) => (
          <m.div
            key={msg.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
          >
            {msg.role === "user" && <LandingUserBubble content={msg.content} />}
            {msg.role === "thinking" && (
              <SimpleChatBubbleBot>
                <MiniWaveSpinner />
              </SimpleChatBubbleBot>
            )}
            {msg.role === "tools" && msg.tools && (
              <ToolCallWrapper
                msgId={msg.id}
                tools={msg.tools}
                expandedIds={expandedIds}
                onToggle={toggleExpand}
              />
            )}
            {msg.role === "assistant" && (
              <SimpleChatBubbleBot>{msg.content}</SimpleChatBubbleBot>
            )}
            {msg.role === "card" && msg.cardContent}
          </m.div>
        ))}
      </div>
    </div>
  );
}

// ─── Inbox Summary Card ───────────────────────────────────────────────

const INBOX_ITEMS = [
  { id: "ii-1", text: "Sequoia term sheet follow-up — reply drafted" },
  { id: "ii-2", text: "Acme customer escalation — summary ready" },
  { id: "ii-3", text: "a16z intro request — response prepped" },
];

function InboxSummaryCard() {
  return (
    <div className="mb-3 pl-[47px]">
      <div className="rounded-2xl bg-zinc-800 p-4">
        <div className="mb-3 flex items-center gap-2">
          <Image
            src="/images/icons/macos/gmail.webp"
            width={16}
            height={16}
            alt="Gmail"
            className="rounded-sm"
          />
          <span className="text-[11px] font-medium text-zinc-400">
            3 replies drafted
          </span>
        </div>
        <div className="space-y-2.5">
          {INBOX_ITEMS.map((item) => (
            <div key={item.id} className="flex items-start gap-2 text-sm">
              <span className="mt-0.5 shrink-0 text-primary">→</span>
              <span className="text-zinc-300">{item.text}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-zinc-500">Confirm to send all?</p>
      </div>
    </div>
  );
}

// ─── Meeting Context Card ─────────────────────────────────────────────

function MeetingContextCard() {
  return (
    <div className="mb-3 pl-[47px]">
      <div className="rounded-2xl bg-zinc-800 p-4">
        <div className="mb-3 flex items-center gap-2">
          <Image
            src="/images/icons/macos/calendar.webp"
            width={16}
            height={16}
            alt="Calendar"
            className="rounded-sm"
          />
          <span className="text-[11px] font-medium text-zinc-400">
            Meeting brief ready
          </span>
        </div>
        <div className="mb-3">
          <p className="text-sm font-medium text-zinc-100">
            Sarah Chen · Sequoia Capital
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">
            Partner · Led 3 Series A rounds this year
          </p>
        </div>
        <div className="space-y-1.5 text-xs text-zinc-400">
          <p>Last contact: 3 weeks ago (intro from YC partner)</p>
          <p>Open items: Q4 metrics, hiring roadmap, cap table</p>
          <p>Style: Bullet points. Direct. Skip pleasantries.</p>
        </div>
      </div>
    </div>
  );
}

// ─── Static Tool Definitions ──────────────────────────────────────────

const INBOX_READ_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Reading inbox — 23 unread",
  },
  {
    category: "gmail",
    name: "gmail_create_draft",
    message: "Drafting 3 replies",
  },
];

const INBOX_SEND_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "gmail_send_email",
    message: "Sending 3 replies",
  },
];

const MEETING_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Searching email history",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Pulling meeting context",
  },
  {
    category: "notion",
    name: "notion_get_pages",
    message: "Reading CRM notes",
  },
];

// ─── Static Message Arrays ────────────────────────────────────────────

const INBOX_MESSAGES: ChatMessage[] = [
  {
    id: "i1",
    role: "user",
    content: "What needs my attention today?",
  },
  {
    id: "i2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "i3",
    role: "tools",
    content: "",
    tools: INBOX_READ_TOOLS,
    delay: 1100,
  },
  {
    id: "i4",
    role: "card",
    content: "",
    cardContent: <InboxSummaryCard />,
    delay: 500,
  },
  {
    id: "i5",
    role: "user",
    content: "Yes, send them all.",
    delay: 900,
  },
  {
    id: "i6",
    role: "tools",
    content: "",
    tools: INBOX_SEND_TOOLS,
    delay: 700,
  },
  {
    id: "i7",
    role: "assistant",
    content: "Done. Inbox clear. Next briefing at 9am tomorrow.",
    delay: 600,
  },
];

const MEETING_MESSAGES: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    content: "Call with Sarah Chen from Sequoia in 30 minutes.",
  },
  {
    id: "m2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "m3",
    role: "tools",
    content: "",
    tools: MEETING_TOOLS,
    delay: 1200,
  },
  {
    id: "m4",
    role: "card",
    content: "",
    cardContent: <MeetingContextCard />,
    delay: 500,
  },
  {
    id: "m5",
    role: "assistant",
    content:
      "Brief ready. She'll ask about Q1 pipeline and Series A timeline. Lead with retention — she loves churn data.",
    delay: 700,
  },
];

// ─── Workflow Steps Demo ──────────────────────────────────────────────

const WORKFLOW_STEPS = [
  {
    id: "wf-1",
    label: "Reading inbox",
    detail: "23 unread",
    category: "gmail",
  },
  {
    id: "wf-2",
    label: "Checking calendar",
    detail: "4 events today",
    category: "googlecalendar",
  },
  {
    id: "wf-3",
    label: "Compiling metrics",
    detail: "MRR, churn, pipeline",
    category: "googlesheets",
  },
  {
    id: "wf-4",
    label: "Posting to #daily-briefing",
    detail: "via Slack",
    category: "slack",
  },
];

function WorkflowsDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const [currentStep, setCurrentStep] = useState(0);
  const [done, setDone] = useState(false);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    WORKFLOW_STEPS.forEach((_, i) => {
      timersRef.current.push(
        setTimeout(() => setCurrentStep(i + 1), 600 + i * 750),
      );
    });
    timersRef.current.push(
      setTimeout(() => setDone(true), 600 + WORKFLOW_STEPS.length * 750 + 400),
    );

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <m.div
      ref={ref}
      initial={{ opacity: 0, y: 16 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.5, ease }}
      className="rounded-3xl bg-zinc-900 p-5 text-left"
    >
      {/* Card header */}
      <div className="mb-5 rounded-2xl bg-zinc-800 p-4">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-sm font-medium text-zinc-100">
            Daily Founder Briefing
          </span>
          <AnimatePresence mode="wait">
            {done ? (
              <m.div
                key="done"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                <span className="text-[11px] font-medium text-emerald-400">
                  Completed
                </span>
              </m.div>
            ) : (
              <m.div
                key="running"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-1.5 rounded-full bg-primary/15 px-2.5 py-1"
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                <span className="text-[11px] font-medium text-primary">
                  Running
                </span>
              </m.div>
            )}
          </AnimatePresence>
        </div>
        <span className="text-xs text-zinc-500">Every day at 9:00 AM</span>
      </div>

      {/* Steps with real tool icons */}
      <div className="space-y-2">
        {WORKFLOW_STEPS.map((step, i) => {
          const isVisible = currentStep > i;
          const isRunning = currentStep === i + 1 && !done;
          const isDone = currentStep > i + 1 || (done && currentStep > i);

          return (
            <AnimatePresence key={step.id}>
              {isVisible && (
                <m.div
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, ease }}
                  className="flex items-center gap-3 rounded-xl bg-zinc-800/60 px-3 py-2.5"
                >
                  {/* Tool category icon */}
                  <div className="flex h-[22px] w-[22px] shrink-0 items-center justify-center">
                    {getToolCategoryIcon(step.category, {
                      width: 22,
                      height: 22,
                    }) ?? (
                      <div
                        className={`h-2 w-2 rounded-full ${
                          isDone
                            ? "bg-emerald-400"
                            : isRunning
                              ? "animate-pulse bg-primary"
                              : "bg-zinc-600"
                        }`}
                      />
                    )}
                  </div>
                  <span
                    className={`flex-1 text-sm ${isDone ? "text-zinc-400" : "text-zinc-200"}`}
                  >
                    {step.label}
                  </span>
                  <span className="text-[11px] text-zinc-600">
                    {step.detail}
                  </span>
                  {isDone && (
                    <m.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="text-[11px] font-medium text-emerald-400"
                    >
                      Done
                    </m.span>
                  )}
                  {isRunning && (
                    <span className="animate-pulse text-[11px] font-medium text-primary">
                      Running
                    </span>
                  )}
                </m.div>
              )}
            </AnimatePresence>
          );
        })}
      </div>
    </m.div>
  );
}

// ─── Slack Demo ───────────────────────────────────────────────────────

const SLACK_ITEMS = [
  { id: "s1", text: "Auth 2.0 is live for all users" },
  { id: "s2", text: "Dashboard redesign launched" },
  { id: "s3", text: "3 critical API bugs resolved" },
  { id: "s4", text: "Onboarding A/B test complete — v2 wins" },
];

function SlackDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const [visibleCount, setVisibleCount] = useState(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    const t1 = setTimeout(() => setVisibleCount(1), 400);
    const t2 = setTimeout(() => setVisibleCount(2), 1400);
    timersRef.current.push(t1, t2);

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <m.div
      ref={ref}
      initial={{ opacity: 0, y: 16 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.5, ease }}
      className="overflow-hidden rounded-3xl bg-zinc-900 text-left"
    >
      {/* Channel header with macOS Slack icon */}
      <div className="flex items-center gap-2 border-b border-zinc-800 px-5 py-3">
        <div className="h-5 w-5 shrink-0 overflow-hidden rounded-md">
          <Image
            src="/images/icons/macos/slack.webp"
            width={20}
            height={20}
            alt="Slack"
            className="h-full w-full object-cover"
          />
        </div>
        <span className="text-sm font-semibold text-zinc-200">gaia</span>
      </div>

      {/* Messages */}
      <div className="min-h-[200px] space-y-5 p-5">
        {/* User question */}
        {visibleCount >= 1 && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-start gap-3"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg">
              <Image
                src="/images/avatars/default.webp"
                width={36}
                height={36}
                alt="User"
                className="h-full w-full object-cover"
              />
            </div>
            <div>
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-sm font-bold text-zinc-100">You</span>
                <span className="text-[11px] text-zinc-600">9:03 AM</span>
              </div>
              <p className="text-sm text-zinc-300">
                <span className="font-semibold text-primary">@GAIA</span> What
                did we ship last week?
              </p>
            </div>
          </m.div>
        )}

        {/* GAIA response */}
        {visibleCount >= 2 && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-start gap-3"
          >
            <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg">
              <Image
                src="/images/logos/logo.webp"
                width={36}
                height={36}
                alt="GAIA"
                className="h-full w-full object-cover"
              />
            </div>
            <div>
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-sm font-bold text-zinc-100">GAIA</span>
                <span className="rounded-sm bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  App
                </span>
                <span className="text-[11px] text-zinc-600">9:03 AM</span>
              </div>
              <div className="text-sm text-zinc-300">
                <p className="mb-2">Here&apos;s what shipped last week:</p>
                <div className="space-y-1">
                  {SLACK_ITEMS.map((item) => (
                    <div key={item.id} className="flex items-start gap-2">
                      <span className="mt-0.5 shrink-0 text-primary">•</span>
                      <span>{item.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </m.div>
        )}
      </div>

      {/* Integration row */}
      <div className="flex items-center gap-3 border-t border-zinc-800 px-5 py-3">
        <span className="text-[11px] text-zinc-600">Connected to</span>
        {(
          [
            { src: "/images/icons/macos/github.webp", alt: "GitHub" },
            { src: "/images/icons/macos/linear.webp", alt: "Linear" },
            { src: "/images/icons/macos/notion.webp", alt: "Notion" },
            { src: "/images/icons/macos/gmail.webp", alt: "Gmail" },
          ] as const
        ).map((icon) => (
          <div
            key={icon.alt}
            className="h-5 w-5 overflow-hidden rounded-md opacity-60"
          >
            <Image
              src={icon.src}
              width={20}
              height={20}
              alt={icon.alt}
              className="h-full w-full object-cover"
            />
          </div>
        ))}
      </div>
    </m.div>
  );
}

// ─── Investor Update Demo ─────────────────────────────────────────────

const METRICS = [
  { id: "mrr", label: "MRR", value: "$47,200", change: "+24%" },
  { id: "cust", label: "Customers", value: "312", change: "+18" },
  { id: "churn", label: "Churn", value: "1.2%", change: "↓0.3%" },
];

function InvestorUpdateDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const [phase, setPhase] = useState<"idle" | "drafting" | "ready">("idle");
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    timersRef.current.push(setTimeout(() => setPhase("drafting"), 400));
    timersRef.current.push(setTimeout(() => setPhase("ready"), 2200));

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <m.div
      ref={ref}
      initial={{ opacity: 0, y: 16 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.5, ease }}
      className="rounded-3xl bg-zinc-900 p-5 text-left"
    >
      {/* Header */}
      <div className="mb-5 flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-zinc-100">
            February 2026 Update
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">
            12 investors · Auto-drafted by GAIA
          </p>
        </div>
        <AnimatePresence mode="wait">
          {phase === "drafting" && (
            <m.div
              key="drafting"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-1.5 rounded-full bg-zinc-800 px-3 py-1"
            >
              <MiniWaveSpinner />
              <span className="text-[11px] text-zinc-400">Drafting…</span>
            </m.div>
          )}
          {phase === "ready" && (
            <m.div
              key="ready"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-3 py-1"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span className="text-[11px] font-medium text-emerald-400">
                Ready to send
              </span>
            </m.div>
          )}
        </AnimatePresence>
      </div>

      {/* Metrics */}
      <AnimatePresence>
        {phase !== "idle" && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="mb-5 grid grid-cols-3 gap-3"
          >
            {METRICS.map((metric) => (
              <div key={metric.id} className="rounded-2xl bg-zinc-800 p-3">
                <p className="mb-1 text-xs text-zinc-500">{metric.label}</p>
                <p className="text-base font-medium text-white">
                  {metric.value}
                </p>
                <p className="mt-0.5 text-[11px] text-emerald-400">
                  {metric.change}
                </p>
              </div>
            ))}
          </m.div>
        )}
      </AnimatePresence>

      {/* Email preview from FOUNDER_EMAIL */}
      <AnimatePresence>
        {phase === "ready" && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.08 }}
            className="mb-5 rounded-2xl bg-zinc-800 p-4"
          >
            <div className="mb-3 flex items-center gap-2">
              <Image
                src="/images/icons/macos/gmail.webp"
                width={16}
                height={16}
                alt="Gmail"
                className="rounded-sm"
              />
              <span className="text-[11px] text-zinc-400">
                Draft · {FOUNDER_EMAIL.to[0]}
              </span>
            </div>
            <p className="mb-2 text-sm font-medium text-zinc-100">
              {FOUNDER_EMAIL.subject}
            </p>
            <p className="line-clamp-3 whitespace-pre-line text-[11px] leading-relaxed text-zinc-500">
              {FOUNDER_EMAIL.body}
            </p>
          </m.div>
        )}
      </AnimatePresence>

      {/* Send CTA */}
      <AnimatePresence>
        {phase === "ready" && (
          <m.button
            type="button"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.18 }}
            className="w-full rounded-2xl bg-primary py-2.5 text-sm font-medium text-black"
          >
            Send to 12 investors
          </m.button>
        )}
      </AnimatePresence>
    </m.div>
  );
}

// ─── Hero ─────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="flex min-h-[90vh] flex-col items-center justify-center px-6 pb-16 pt-24 text-center">
      <m.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease }}
        className="mb-6 rounded-full border border-primary/20 bg-primary/10 px-4 py-1.5 text-xs font-medium uppercase tracking-widest text-primary"
      >
        Built for founders
      </m.div>
      <m.h1
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.1 }}
        className="font-serif mb-6 max-w-3xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
      >
        You didn&apos;t start a company to manage your inbox.
      </m.h1>
      <m.p
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.2 }}
        className="mb-10 max-w-xl text-xl font-light leading-relaxed text-zinc-400"
      >
        GAIA is your AI chief of staff. It runs your workflows, drafts investor
        updates, triages your inbox, and preps every meeting — automatically.
      </m.p>
      <m.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.3 }}
      >
        <GetStartedButton
          text="See GAIA in action"
          btnColor="#00bbff"
          classname="text-black! text-base h-12 rounded-xl"
        />
      </m.div>
    </section>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────

export default function FoundersClient() {
  return (
    <div className="w-full">
      <Hero />

      {/* Inbox Zero */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Inbox Zero"
          headline="Your inbox. Answered, filed, and done."
          description="GAIA reads every email, surfaces what needs your attention, and drafts replies in your voice. Investor follow-ups, customer questions, intro requests — handled before your first coffee."
        />
        <m.div
          className="w-full max-w-lg"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.2 }}
          transition={{ duration: 0.6, ease }}
        >
          <ChatDemo messages={INBOX_MESSAGES} minHeight={280} />
        </m.div>
      </section>

      {/* On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Set it once. Never think about it again."
          description="Tell GAIA what you need — a daily briefing at 9am, weekly team updates, expense reports on the first of the month. It builds the steps, sets the schedule, and runs on repeat."
        />
        <div className="w-full max-w-lg">
          <WorkflowsDemo />
        </div>
      </section>

      {/* In Your Stack */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="In Your Stack"
          headline="GAIA lives where your team already works."
          description="Ask GAIA anything in Slack. Get instant answers from your docs, your calendar, your CRM. No tab-switching, no context switching. Your company's knowledge, in the channel where decisions happen."
        />
        <div className="w-full max-w-lg">
          <SlackDemo />
        </div>
      </section>

      {/* Every Meeting */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Every Meeting"
          headline="Walk in prepared. Walk out with a plan."
          description="GAIA pulls context on everyone you're meeting — their background, your history, open threads. After the call, it writes the follow-up and captures action items automatically."
        />
        <m.div
          className="w-full max-w-lg"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.2 }}
          transition={{ duration: 0.6, ease }}
        >
          <ChatDemo messages={MEETING_MESSAGES} minHeight={260} />
        </m.div>
      </section>

      {/* Investor Updates */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Investor Updates"
          headline="Never miss an investor update again."
          description="GAIA drafts your monthly update from your metrics, wins, and blockers. It tracks every investor conversation and makes sure no warm relationship goes cold."
        />
        <div className="w-full max-w-lg">
          <InvestorUpdateDemo />
        </div>
      </section>

      <FinalSection />
    </div>
  );
}
