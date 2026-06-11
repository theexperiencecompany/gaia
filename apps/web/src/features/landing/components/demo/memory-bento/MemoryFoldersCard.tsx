"use client";

import { FolderIcon, SparklesIcon } from "@icons";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

const ease = [0.25, 0.1, 0.25, 1] as const;

const FOLDERS = [
  { name: "People", count: 24, highlight: true },
  { name: "Food & places", count: 18, highlight: false },
  { name: "Work", count: 31, highlight: false },
  { name: "Health", count: 9, highlight: false },
];

export default function MemoryFoldersCard() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="flex h-full flex-col gap-2">
      <m.div
        className="flex items-center gap-2 rounded-2xl bg-zinc-900 p-3"
        initial={{ opacity: 0, y: -10 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: -10 }}
        transition={{ duration: 0.35, ease }}
      >
        <SparklesIcon className="size-4 shrink-0 text-indigo-400" />
        <span className="text-xs text-zinc-300">
          Noted from your chat: Maya only eats vegetarian
        </span>
      </m.div>

      <div className="flex flex-1 flex-col gap-2">
        {FOLDERS.map((folder, index) => (
          <m.div
            key={folder.name}
            className="flex items-center justify-between rounded-2xl bg-zinc-900 p-3"
            initial={{ opacity: 0, x: -12 }}
            animate={isInView ? { opacity: 1, x: 0 } : { opacity: 0, x: -12 }}
            transition={{ duration: 0.3, ease, delay: 0.25 + index * 0.12 }}
          >
            <div className="flex items-center gap-2">
              <FolderIcon className="size-4 shrink-0 text-zinc-400" />
              <span className="text-sm text-zinc-200">{folder.name}</span>
            </div>
            <div className="flex items-center gap-2">
              {folder.highlight && (
                <m.span
                  className="rounded-full bg-indigo-500/20 px-2 py-0.5 text-[10px] font-medium text-indigo-400"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={
                    isInView
                      ? { opacity: 1, scale: 1 }
                      : { opacity: 0, scale: 0.8 }
                  }
                  transition={{ duration: 0.3, ease, delay: 0.9 }}
                >
                  +1 new
                </m.span>
              )}
              <span className="text-xs tabular-nums text-zinc-500">
                {folder.count}
              </span>
            </div>
          </m.div>
        ))}
      </div>
    </div>
  );
}
