"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface Tool {
  name: string;
  category: string;
}

interface ToolsListProps {
  tools: Tool[];
}

export default function ToolsList({ tools }: ToolsListProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!tools || tools.length === 0) return null;

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  const displayIcons = tools.slice(0, 3);

  return (
    <div className="inline-block" onClick={toggleExpanded}>
      <AnimatePresence mode="wait">
        {!isExpanded ? (
          // Collapsed state - single card showing count and icons
          <motion.div
            key="collapsed"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex h-[52px] cursor-pointer items-center gap-2.5 rounded-2xl bg-zinc-900 px-4 py-2 transition-colors hover:bg-zinc-800"
          >
            <div className="flex min-h-8 items-center -space-x-1.5">
              {displayIcons.map((t, i) => {
                const Icon = getToolCategoryIcon(t.category, {
                  width: 25,
                  height: 25,
                });
                return (
                  <div
                    key={t.name}
                    className="relative flex min-w-8 items-center justify-center"
                    style={{
                      rotate:
                        displayIcons.length > 1
                          ? i % 2 === 0
                            ? "8deg"
                            : "-8deg"
                          : "0deg",
                      zIndex: i,
                    }}
                  >
                    {Icon}
                  </div>
                );
              })}
            </div>
            <span className="text-sm font-medium whitespace-nowrap text-foreground">
              {tools.length} {tools.length === 1 ? "Tool" : "Tools"}
            </span>
          </motion.div>
        ) : (
          // Expanded state - stacked list of all tools
          <motion.div
            key="expanded"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="flex min-w-[240px] flex-col gap-2"
          >
            {tools.map((tool, index) => {
              const IconComponent = getToolCategoryIcon(tool.category, {
                width: 25,
                height: 25,
              });

              return (
                <motion.div
                  key={tool.name}
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="cursor-pointer rounded-2xl bg-zinc-900 px-4 py-2 transition-colors hover:bg-zinc-800"
                >
                  <div className="flex items-center gap-2">
                    {IconComponent}
                    <span className="text-sm text-foreground">
                      {formatToolName(tool.name)}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
