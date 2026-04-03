"use client";

import { AnimatePresence, m, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

// ─── Constants ─────────────────────────────────────────────────────────────────

const SERVER_URL = "https://mcp.github-tools.io/v1";

const ease = [0.22, 1, 0.36, 1] as const;

interface Tool {
  id: string;
  name: string;
  description: string;
}

const MCP_TOOLS: Tool[] = [
  { id: "t1", name: "list_repositories", description: "List GitHub repos" },
  { id: "t2", name: "create_issue", description: "Create a new issue" },
  { id: "t3", name: "search_code", description: "Search code across repos" },
  { id: "t4", name: "get_pull_request", description: "Get PR details" },
  { id: "t5", name: "add_comment", description: "Add review comment" },
];

const TIMINGS = {
  connectingDelay: 800,
  connectedDelay: 2200,
};

// ─── Stage types ───────────────────────────────────────────────────────────────

type Stage = "idle" | "connecting" | "connected";

// ─── MCPSupportDemo ────────────────────────────────────────────────────────────

export default function MCPSupportDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const [stage, setStage] = useState<Stage>("idle");

  useEffect(() => {
    if (!inView) return;

    const add = (fn: () => void, delay: number) => {
      timersRef.current.push(setTimeout(fn, delay));
    };

    const captured = timersRef.current;

    add(() => setStage("connecting"), TIMINGS.connectingDelay);
    add(() => setStage("connected"), TIMINGS.connectedDelay);

    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <div ref={ref} className="rounded-2xl bg-zinc-800 p-4">
      {/* Server URL input row */}
      <div className="mb-3 flex items-center gap-2">
        <span className="shrink-0 text-xs text-zinc-500">Server URL</span>
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl bg-zinc-900 px-3 py-2">
          <span className="flex-1 truncate font-mono text-xs text-zinc-300">
            {SERVER_URL}
          </span>
        </div>
        <div className="shrink-0 rounded-xl bg-[#00bbff]/10 px-3 py-2">
          <span className="text-xs font-medium text-[#00bbff]">Connect</span>
        </div>
      </div>

      {/* Connecting row */}
      <AnimatePresence>
        {stage === "connecting" && (
          <m.div
            key="connecting"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease }}
            className="mb-3 flex items-center gap-2 rounded-xl bg-zinc-900 px-3 py-2.5"
          >
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-zinc-600 border-t-[#00bbff]" />
            <span className="text-xs text-zinc-400">
              Connecting to MCP server...
            </span>
          </m.div>
        )}
      </AnimatePresence>

      {/* Connected tools panel */}
      <AnimatePresence>
        {stage === "connected" && (
          <m.div
            key="connected"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
          >
            {/* Connected header */}
            <div className="mb-2 flex items-center gap-1.5">
              <span className="text-xs font-medium text-emerald-400">
                ✓ Connected
              </span>
              <span className="text-xs text-zinc-500">·</span>
              <span className="text-xs text-zinc-500">5 tools available</span>
            </div>

            {/* Tools list */}
            <div className="rounded-xl bg-zinc-900 px-3">
              {MCP_TOOLS.map((tool) => (
                <div
                  key={tool.id}
                  className="flex items-center gap-2 border-b border-zinc-800 py-2 last:border-0"
                >
                  <span className="font-mono text-xs text-[#00bbff]">
                    {tool.name}
                  </span>
                  <span className="text-xs text-zinc-500">
                    — {tool.description}
                  </span>
                </div>
              ))}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
