"use client";

import { ArrowDown01Icon, FolderIcon, SparklesIcon } from "@icons";
import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef, useState } from "react";

const ease = [0.25, 0.1, 0.25, 1] as const;

const DEFAULT_CAPTION = "Noted from your chat: Maya only eats vegetarian";

interface FolderMemory {
  text: string;
  caption: string;
}

interface Folder {
  name: string;
  count: number;
  highlight: boolean;
  memories: FolderMemory[];
}

const FOLDERS: Folder[] = [
  {
    name: "People",
    count: 24,
    highlight: true,
    memories: [
      {
        text: "Maya only eats vegetarian",
        caption: "Noted from your chat: Maya only eats vegetarian",
      },
      {
        text: "Sam's birthday is March 12",
        caption: "Noted from your chat: Sam's birthday is March 12",
      },
      {
        text: "Priya prefers calls over email",
        caption: "Noted from your chat: Priya prefers calls over email",
      },
    ],
  },
  {
    name: "Food & places",
    count: 18,
    highlight: false,
    memories: [
      {
        text: "Loves the window table at Osteria Verde",
        caption: "Noted from your chat: you love the window table there",
      },
      {
        text: "No cilantro, ever",
        caption: "Noted from your chat: no cilantro, ever",
      },
    ],
  },
  {
    name: "Work",
    count: 31,
    highlight: false,
    memories: [
      {
        text: "Standup moved to 9:30 on weekdays",
        caption: "Noted from your chat: standup is 9:30 now",
      },
      {
        text: "Q3 launch is the priority this quarter",
        caption: "Noted from your chat: Q3 launch comes first",
      },
    ],
  },
  {
    name: "Health",
    count: 9,
    highlight: false,
    memories: [
      {
        text: "Gym evenings, 7 to 8",
        caption: "Noted from your chat: gym evenings, 7 to 8",
      },
    ],
  },
];

export default function MemoryFoldersCard() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });
  const [expanded, setExpanded] = useState<string | null>("People");
  const [caption, setCaption] = useState(DEFAULT_CAPTION);

  return (
    <div ref={ref} className="flex h-full flex-col gap-2">
      <m.div
        className="flex items-center gap-2 rounded-2xl bg-zinc-900 p-3"
        initial={{ opacity: 0, y: -10 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: -10 }}
        transition={{ duration: 0.35, ease }}
      >
        <SparklesIcon className="size-4 shrink-0 text-blue-400" />
        <AnimatePresence mode="wait" initial={false}>
          <m.span
            key={caption}
            className="text-xs text-zinc-300"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease }}
          >
            {caption}
          </m.span>
        </AnimatePresence>
      </m.div>

      <div className="flex flex-1 flex-col gap-2">
        {FOLDERS.map((folder, index) => {
          const isOpen = expanded === folder.name;
          return (
            <m.div
              key={folder.name}
              className="overflow-hidden rounded-2xl bg-zinc-900"
              initial={{ opacity: 0, x: -12 }}
              animate={isInView ? { opacity: 1, x: 0 } : { opacity: 0, x: -12 }}
              transition={{ duration: 0.3, ease, delay: 0.25 + index * 0.12 }}
            >
              <button
                type="button"
                className="flex w-full cursor-pointer items-center justify-between p-3 text-left"
                onClick={() => setExpanded(isOpen ? null : folder.name)}
              >
                <div className="flex items-center gap-2">
                  <FolderIcon className="size-4 shrink-0 text-zinc-400" />
                  <span className="text-sm text-zinc-200">{folder.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  {folder.highlight && (
                    <m.span
                      className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] font-medium text-blue-400"
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
                  <ArrowDown01Icon
                    className={`size-3.5 text-zinc-600 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                  />
                </div>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <m.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.22, ease }}
                  >
                    <div className="flex flex-col gap-1 px-3 pb-3">
                      {folder.memories.map((memory) => (
                        <div
                          key={memory.text}
                          className="cursor-default rounded-xl px-2 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
                          onMouseEnter={() => setCaption(memory.caption)}
                          onMouseLeave={() => setCaption(DEFAULT_CAPTION)}
                        >
                          {memory.text}
                        </div>
                      ))}
                    </div>
                  </m.div>
                )}
              </AnimatePresence>
            </m.div>
          );
        })}
      </div>
    </div>
  );
}
