"use client";

import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface Skill {
  id: string;
  name: string;
  description: string;
  status: "installed" | "animated";
}

// ─── Data ──────────────────────────────────────────────────────────────────────

const SKILLS: Skill[] = [
  {
    id: "gmail",
    name: "Gmail Workflows",
    description: "Automate inbox triage and replies",
    status: "installed",
  },
  {
    id: "github",
    name: "GitHub PRs",
    description: "Review, summarize, and comment on pull requests",
    status: "installed",
  },
  {
    id: "slack",
    name: "Slack Digest",
    description: "Daily channel summaries and thread monitoring",
    status: "installed",
  },
  {
    id: "notion",
    name: "Notion Sync",
    description: "Sync tasks and notes with Notion workspace",
    status: "animated",
  },
];

// ─── Installed Badge ───────────────────────────────────────────────────────────

function InstalledBadge() {
  return (
    <span className="shrink-0 text-xs font-medium text-emerald-400">
      ✓ Installed
    </span>
  );
}

// ─── Animating Badge ──────────────────────────────────────────────────────────

interface AnimatingBadgeProps {
  started: boolean;
  onComplete: () => void;
}

function AnimatingBadge({ started, onComplete }: AnimatingBadgeProps) {
  return (
    <div className="shrink-0 w-24 h-4 rounded-full bg-zinc-700 overflow-hidden">
      {started && (
        <m.div
          className="h-full rounded-full bg-cyan-400"
          initial={{ width: "0%" }}
          animate={{ width: "100%" }}
          transition={{ duration: 1.5, ease: "easeInOut" }}
          onAnimationComplete={onComplete}
        />
      )}
    </div>
  );
}

// ─── Skill Row ─────────────────────────────────────────────────────────────────

interface SkillRowProps {
  skill: Skill;
  isLast: boolean;
  animationStarted: boolean;
  onBarComplete: () => void;
  showDone: boolean;
}

function SkillRow({
  skill,
  isLast,
  animationStarted,
  onBarComplete,
  showDone,
}: SkillRowProps) {
  return (
    <div
      className={`flex items-center gap-3 py-3 ${!isLast ? "border-b border-zinc-800" : ""}`}
    >
      <div className="rounded-lg bg-zinc-700 w-8 h-8 shrink-0 flex items-center justify-center">
        <span className="text-xs font-semibold text-zinc-300">
          {skill.name[0]}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-zinc-200">{skill.name}</p>
        <p className="text-xs text-zinc-500">{skill.description}</p>
      </div>
      {skill.status === "installed" ? (
        <InstalledBadge />
      ) : (
        <AnimatePresence mode="wait">
          {showDone ? (
            <m.span
              key="done"
              className="shrink-0 text-xs font-medium text-emerald-400"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
            >
              ✓ Installed
            </m.span>
          ) : (
            <m.div
              key="bar"
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <AnimatingBadge
                started={animationStarted}
                onComplete={onBarComplete}
              />
            </m.div>
          )}
        </AnimatePresence>
      )}
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export default function SkillsDemo() {
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, margin: "-50px" });
  const [barStarted, setBarStarted] = useState(false);
  const [showDone, setShowDone] = useState(false);

  useEffect(() => {
    if (!isInView) return;

    const timer = setTimeout(() => {
      setBarStarted(true);
    }, 500);

    return () => clearTimeout(timer);
  }, [isInView]);

  function handleBarComplete() {
    setShowDone(true);
  }

  return (
    <div ref={containerRef} className="rounded-2xl bg-zinc-800 px-4">
      {SKILLS.map((skill, index) => (
        <SkillRow
          key={skill.id}
          skill={skill}
          isLast={index === SKILLS.length - 1}
          animationStarted={skill.status === "animated" ? barStarted : false}
          onBarComplete={handleBarComplete}
          showDone={skill.status === "animated" ? showDone : false}
        />
      ))}
    </div>
  );
}
