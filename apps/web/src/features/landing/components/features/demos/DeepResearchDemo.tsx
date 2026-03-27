"use client";

import { AnimatePresence, m, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

// ─── Constants ─────────────────────────────────────────────────────────────────

const SEARCH_QUERY = "What are the best approaches to B2B SaaS pricing?";

const ease = [0.22, 1, 0.36, 1] as const;

type SourceStatus = "searching" | "reading" | "done";

interface Source {
  id: string;
  title: string;
  author: string;
  color: string;
  initials: string;
}

const SOURCES: Source[] = [
  {
    id: "s1",
    title: "SaaS Pricing Guide",
    author: "OpenView Partners",
    color: "bg-blue-500",
    initials: "OV",
  },
  {
    id: "s2",
    title: "Pricing Study",
    author: "Patrick Campbell, ProfitWell",
    color: "bg-purple-500",
    initials: "PC",
  },
  {
    id: "s3",
    title: "Value-based Pricing",
    author: "HBR",
    color: "bg-rose-500",
    initials: "HB",
  },
];

// Each source takes 2s per status phase: searching → reading → done
// Source 0: starts at 0ms
// Source 1: starts at 500ms (0.5s stagger)
// Source 2: starts at 1000ms (1s stagger)
// Summary appears after all sources are done
const TIMINGS = {
  source0Start: 200,
  source1Start: 700,
  source2Start: 1200,
  statusPhaseDuration: 2000,
  summaryDelay: 200,
};

// ─── SourceCard ────────────────────────────────────────────────────────────────

interface SourceCardProps {
  source: Source;
  status: SourceStatus;
}

function StatusLabel({ status }: { status: SourceStatus }) {
  return (
    <AnimatePresence mode="wait">
      {status === "searching" && (
        <m.span
          key="searching"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="text-xs text-zinc-500"
        >
          searching...
        </m.span>
      )}
      {status === "reading" && (
        <m.span
          key="reading"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="text-xs text-yellow-400"
        >
          reading...
        </m.span>
      )}
      {status === "done" && (
        <m.span
          key="done"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="text-xs font-medium text-green-400"
        >
          ✓ done
        </m.span>
      )}
    </AnimatePresence>
  );
}

function SourceCard({ source, status }: SourceCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-xl bg-zinc-700/50 p-3">
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${source.color} text-[10px] font-bold text-white`}
      >
        {source.initials}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {source.title}
        </p>
        <p className="truncate text-xs text-zinc-500">{source.author}</p>
      </div>
      <StatusLabel status={status} />
    </div>
  );
}

// ─── DeepResearchDemo ──────────────────────────────────────────────────────────

export default function DeepResearchDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const [visibleSources, setVisibleSources] = useState<number>(0);
  const [statuses, setStatuses] = useState<SourceStatus[]>([
    "searching",
    "searching",
    "searching",
  ]);
  const [showSummary, setShowSummary] = useState(false);

  useEffect(() => {
    if (!inView) return;

    const add = (fn: () => void, delay: number) => {
      timersRef.current.push(setTimeout(fn, delay));
    };

    const captured = timersRef.current;

    // Source 0
    add(() => setVisibleSources(1), TIMINGS.source0Start);
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[0] = "reading";
          return next;
        }),
      TIMINGS.source0Start + TIMINGS.statusPhaseDuration,
    );
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[0] = "done";
          return next;
        }),
      TIMINGS.source0Start + TIMINGS.statusPhaseDuration * 2,
    );

    // Source 1
    add(() => setVisibleSources(2), TIMINGS.source1Start);
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[1] = "reading";
          return next;
        }),
      TIMINGS.source1Start + TIMINGS.statusPhaseDuration,
    );
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[1] = "done";
          return next;
        }),
      TIMINGS.source1Start + TIMINGS.statusPhaseDuration * 2,
    );

    // Source 2
    add(() => setVisibleSources(3), TIMINGS.source2Start);
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[2] = "reading";
          return next;
        }),
      TIMINGS.source2Start + TIMINGS.statusPhaseDuration,
    );
    add(
      () =>
        setStatuses((prev) => {
          const next = [...prev] as SourceStatus[];
          next[2] = "done";
          return next;
        }),
      TIMINGS.source2Start + TIMINGS.statusPhaseDuration * 2,
    );

    // Summary — after all sources are done
    const allDoneAt =
      TIMINGS.source2Start +
      TIMINGS.statusPhaseDuration * 2 +
      TIMINGS.summaryDelay;
    add(() => setShowSummary(true), allDoneAt);

    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <div
      ref={ref}
      className="flex flex-col gap-3 overflow-hidden rounded-3xl bg-zinc-900 p-5"
    >
      {/* Search query */}
      <div className="rounded-xl bg-zinc-800 px-3 py-2.5">
        <p className="text-xs text-zinc-500">Research query</p>
        <p className="mt-0.5 text-sm font-medium text-zinc-200">
          {SEARCH_QUERY}
        </p>
      </div>

      {/* Source cards */}
      <div className="space-y-2">
        {SOURCES.map((source, i) => (
          <AnimatePresence key={source.id}>
            {visibleSources > i && (
              <m.div
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.35, ease }}
              >
                <SourceCard source={source} status={statuses[i]} />
              </m.div>
            )}
          </AnimatePresence>
        ))}
      </div>

      {/* Summary card */}
      <AnimatePresence>
        {showSummary && (
          <m.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease }}
            className="rounded-xl border border-[#00bbff]/20 bg-[#00bbff]/10 p-3 text-xs text-[#00bbff]"
          >
            3 sources analyzed · 12 citations extracted · Synthesis ready
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
