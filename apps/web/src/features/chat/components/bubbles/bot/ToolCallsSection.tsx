"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { useState } from "react";

import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { ChevronDown, ToolsIcon } from "@/icons";

interface ToolCallsSectionProps {
  tool_calls_data: ToolCallEntry[];
}

/**
 * Format tool name for display
 * Converts snake_case to Title Case
 */
function formatToolName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function ToolCallsSection({
  tool_calls_data,
}: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const SHOWICONS = 10;
  if (tool_calls_data.length === 0) return null;

  // Render stacked rotated icons (deduplicated by category for cleaner display)
  const renderStackedIcons = () => {
    const seenCategories = new Set<string>();
    const uniqueIcons = tool_calls_data.filter((call) => {
      const category = call.tool_category || "general";
      if (seenCategories.has(category)) return false;
      seenCategories.add(category);
      return true;
    });
    const displayIcons = uniqueIcons.slice(0, SHOWICONS);

    return (
      <div className="flex min-h-8 items-center -space-x-1.5">
        {displayIcons.map((call, index) => {
          const IconComponent = getToolCategoryIcon(
            call.tool_category || "general",
            {
              width: 21,
              height: 21,
            },
          );
          return IconComponent ? (
            <div
              key={`${call.tool_name}-${index}`}
              className="relative flex min-w-8 items-center justify-center"
              style={{
                rotate:
                  displayIcons.length > 1
                    ? index % 2 === 0
                      ? "8deg"
                      : "-8deg"
                    : "0deg",
                zIndex: index,
              }}
            >
              {IconComponent}
            </div>
          ) : null;
        })}
        {tool_calls_data.length > SHOWICONS && (
          <div className="z-0 flex size-8.5 min-h-8.5 min-w-8.5 items-center justify-center rounded-lg bg-zinc-700/60 text-sm text-foreground-500">
            +{tool_calls_data.length - SHOWICONS}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-fit max-w-100">
      <Accordion
        variant="light"
        isCompact
        hideIndicator
        selectedKeys={isExpanded ? new Set(["tools"]) : new Set([])}
        onSelectionChange={(keys) => {
          const expanded =
            keys === "all" || (keys instanceof Set && keys.has("tools"));
          setIsExpanded(expanded);
        }}
        style={{ padding: 0 }}
        itemClasses={{
          trigger: "cursor-pointer ",
        }}
      >
        <AccordionItem
          key="tools"
          title={
            <div className="flex items-center gap-2 hover:text-white text-zinc-500 ">
              {!isExpanded && renderStackedIcons()}
              <span className="text-xs font-medium transition-all duration-200">
                Used {tool_calls_data.length} tool
                {tool_calls_data.length > 1 ? "s" : ""}
              </span>
              <ChevronDown
                className={`${isExpanded ? "rotate-180" : ""} transition-all duration-200`}
                width={18}
                height={18}
              />
            </div>
          }
        >
          <div className="space-y-0 pl-1">
            {tool_calls_data.map((call, index) => {
              const hasCategoryText =
                call.show_category !== false &&
                call.tool_category &&
                call.tool_category !== "unknown";

              return (
                <div
                  key={`${call.tool_name}-step-${index}`}
                  className="flex items-start gap-2"
                >
                  <div className="flex flex-col items-center justify-center">
                    <div className="min-h-8 min-w-8 flex items-center justify-center">
                      {getToolCategoryIcon(call.tool_category || "general", {
                        size: 21,
                        width: 21,
                        height: 21,
                      }) || (
                        <div className="p-1 bg-zinc-800 rounded-lg">
                          <ToolsIcon width={21} height={21} />
                        </div>
                      )}
                    </div>
                    {index < tool_calls_data.length - 1 && (
                      <div className="w-px h-4 bg-default-200" />
                    )}
                  </div>

                  <div className="flex-1">
                    <p
                      className={`text-xs text-zinc-300 font-medium ${!hasCategoryText ? "pt-2" : ""}`}
                    >
                      {call.message || formatToolName(call.tool_name)}
                    </p>
                    {hasCategoryText && (
                      <p className="text-[11px] text-default-400 capitalize">
                        {call.tool_category.replace(/_/g, " ")}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
