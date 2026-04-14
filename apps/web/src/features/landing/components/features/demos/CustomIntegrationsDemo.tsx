"use client";

import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";

type Stage = "form" | "creating" | "success";

export default function CustomIntegrationsDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });
  const [stage, setStage] = useState<Stage>("form");
  const [progressWidth, setProgressWidth] = useState(0);

  useEffect(() => {
    if (!inView) return;

    const t1 = setTimeout(() => {
      setStage("creating");
    }, 1000);

    const t2 = setTimeout(() => {
      setProgressWidth(100);
    }, 1200);

    const t3 = setTimeout(() => {
      setStage("success");
    }, 2500);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [inView]);

  return (
    <div ref={ref} className="rounded-2xl bg-zinc-800 p-5 w-full">
      <AnimatePresence mode="wait">
        {stage !== "success" ? (
          <m.div
            key="form"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <span className="text-xs text-zinc-500">Name</span>
              <div className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-zinc-300">
                Notion Tasks Sync
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-xs text-zinc-500">URL</span>
              <div className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-zinc-300">
                https://api.notion.com/v1
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-xs text-zinc-500">Auth</span>
              <div className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-zinc-300 flex items-center justify-between">
                <span>Bearer Token</span>
                <span className="text-zinc-500">▼</span>
              </div>
            </div>

            <div className="flex items-center gap-2 py-1">
              <div className="h-4 w-4 rounded border border-zinc-600 bg-zinc-900 flex items-center justify-center shrink-0">
                <div className="h-2 w-2 rounded-sm bg-zinc-600" />
              </div>
              <span className="text-xs text-zinc-400">
                Publish to Marketplace
              </span>
            </div>

            <AnimatePresence>
              {stage === "creating" && (
                <m.div
                  key="progress-row"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className="overflow-hidden"
                >
                  <div className="flex flex-col gap-2 pt-1">
                    <span className="text-xs text-zinc-400">
                      Creating integration...
                    </span>
                    <div className="h-1.5 w-full rounded-full bg-zinc-700 overflow-hidden">
                      <m.div
                        className="h-full rounded-full bg-[#00bbff]"
                        initial={{ width: "0%" }}
                        animate={{ width: `${progressWidth}%` }}
                        transition={{ duration: 1.1, ease: "easeInOut" }}
                      />
                    </div>
                  </div>
                </m.div>
              )}
            </AnimatePresence>

            {stage === "form" && (
              <div className="rounded-lg bg-[#00bbff]/10 px-4 py-2 text-sm font-medium text-[#00bbff] text-center w-full mt-1">
                Create Integration
              </div>
            )}
          </m.div>
        ) : (
          <m.div
            key="success"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="rounded-2xl bg-[#00bbff]/5 border border-[#00bbff]/20 p-4 flex flex-col gap-3"
          >
            <div className="flex items-center gap-2">
              <span className="text-[#00bbff] text-base leading-none">✓</span>
              <span className="text-sm font-semibold text-zinc-100">
                Integration Created
              </span>
            </div>

            <p className="text-xs text-zinc-400">
              Notion Tasks Sync · https://api.notion.com/v1
            </p>

            <p className="text-xs text-zinc-400">
              4 tools discovered:{" "}
              <span className="text-zinc-300">
                list_tasks, create_task, update_task, search_pages
              </span>
            </p>

            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-[#00bbff]" />
              <span className="text-xs text-[#00bbff]">
                Published to Marketplace
              </span>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
