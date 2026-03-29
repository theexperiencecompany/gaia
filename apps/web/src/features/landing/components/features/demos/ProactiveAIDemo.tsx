"use client";

import {
  Calendar01Icon,
  Clock01Icon,
  Mail01Icon,
  MessageMultiple01Icon,
  SourceCodeCircleIcon,
} from "@icons";
import { m, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

const BRIEFING_ITEMS = [
  {
    icon: Mail01Icon,
    text: "3 emails need your reply — including Sarah from legal",
  },
  {
    icon: Calendar01Icon,
    text: "2 meetings today — standup at 10am, demo at 3pm",
  },
  {
    icon: SourceCodeCircleIcon,
    text: "PR #47 has been waiting for review 2 days",
  },
  {
    icon: MessageMultiple01Icon,
    text: "Slack thread in #product needs decision by EOD",
  },
];

export default function ProactiveAIDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const [animationKey, setAnimationKey] = useState(0);

  useEffect(() => {
    if (!isInView) return;
    const interval = setInterval(
      () => {
        setAnimationKey((k) => k + 1);
      },
      5000 + BRIEFING_ITEMS.length * 150 + 600,
    );
    return () => clearInterval(interval);
  }, [isInView]);

  return (
    <div ref={ref} className="flex items-center justify-center p-4">
      <m.div
        key={animationKey}
        className="rounded-2xl bg-zinc-800 p-5 w-full max-w-sm"
        initial={{ opacity: 0, y: 32 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 32 }}
        transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
      >
        {/* Header */}
        <div className="flex items-center gap-1.5 mb-1">
          <Clock01Icon className="size-3.5 text-zinc-400" />
          <span className="text-xs text-zinc-400">
            9:00 AM · Your Daily Briefing
          </span>
        </div>

        {/* Date */}
        <p className="text-sm font-medium text-zinc-200 mb-3">
          Friday, March 27
        </p>

        {/* Divider */}
        <div className="h-px bg-zinc-700 mb-3" />

        {/* Items */}
        <div className="space-y-2">
          {BRIEFING_ITEMS.map((item, index) => (
            <m.div
              key={item.text}
              initial={{ opacity: 0, x: -12 }}
              animate={isInView ? { opacity: 1, x: 0 } : { opacity: 0, x: -12 }}
              transition={{
                duration: 0.3,
                ease: [0.25, 0.1, 0.25, 1],
                delay: 0.3 + index * 0.15,
              }}
              onMouseEnter={() => setHoveredIndex(index)}
              onMouseLeave={() => setHoveredIndex(null)}
              className="flex items-start gap-2 py-1.5 px-2 rounded-lg transition-all duration-150 cursor-default"
              style={{
                borderLeft:
                  hoveredIndex === index
                    ? "2px solid rgb(34 211 238)"
                    : "2px solid transparent",
              }}
            >
              <item.icon className="size-3.5 text-zinc-400 shrink-0 mt-0.5" />
              <span className="text-xs text-zinc-300 leading-relaxed">
                {item.text}
              </span>
            </m.div>
          ))}
        </div>

        {/* Footer */}
        <m.p
          initial={{ opacity: 0 }}
          animate={isInView ? { opacity: 1 } : { opacity: 0 }}
          transition={{
            duration: 0.3,
            delay: 0.3 + BRIEFING_ITEMS.length * 0.15 + 0.1,
          }}
          className="text-xs text-zinc-500 mt-3 pt-3 border-t border-zinc-700"
        >
          4 items · Generated 8 minutes ago
        </m.p>
      </m.div>
    </div>
  );
}
