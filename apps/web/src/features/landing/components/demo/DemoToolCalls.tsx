import { AnimatePresence, motion } from "framer-motion";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { ChevronDown, Wrench01Icon } from "@/icons";
import { tx } from "./demoConstants";
import type { ToolStep } from "./types";

interface DemoToolCallsProps {
  tools: ToolStep[];
  expanded: boolean;
  onToggle: () => void;
}

export default function DemoToolCalls({
  tools,
  expanded,
  onToggle,
}: DemoToolCallsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={tx}
      className="w-fit max-w-full"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex cursor-pointer items-center gap-2 py-1 text-zinc-500 transition-colors hover:text-white"
      >
        <div className="flex items-center -space-x-2">
          {tools.map((t, i) => (
            <div
              key={`${t.name}-${i}`}
              className="relative flex h-7 w-7 items-center justify-center"
              style={{ rotate: i % 2 === 0 ? "8deg" : "-8deg", zIndex: i }}
            >
              {getToolCategoryIcon(t.category, { width: 21, height: 21 }) ?? (
                <div className="rounded-lg bg-zinc-800 p-1">
                  <Wrench01Icon width={14} height={14} />
                </div>
              )}
            </div>
          ))}
        </div>
        <span className="text-xs font-medium">Used {tools.length} tools</span>
        <ChevronDown
          className={`${expanded ? "rotate-180" : ""} transition-transform duration-200`}
          width={14}
          height={14}
        />
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="py-1">
              {tools.map((t, i) => (
                <div
                  key={`${t.name}-${i}-detail`}
                  className="flex items-stretch gap-2"
                >
                  <div className="flex flex-col items-center self-stretch">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center">
                      {getToolCategoryIcon(t.category, {
                        size: 20,
                        width: 20,
                        height: 20,
                      }) ?? (
                        <div className="rounded-lg bg-zinc-800 p-1">
                          <Wrench01Icon width={14} height={14} />
                        </div>
                      )}
                    </div>
                    {i < tools.length - 1 && (
                      <div className="min-h-3 w-px flex-1 bg-zinc-700" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="pt-1 text-xs font-medium text-zinc-400">
                      {t.message}
                    </p>
                    <p className="text-[11px] capitalize text-zinc-600">
                      {t.category.replace(/_/g, " ")}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
