"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { useMemo, useState } from "react";

import { CompactMarkdown } from "@/components/ui/CompactMarkdown";
import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { ChevronDown, ToolsIcon } from "@/icons";

interface ToolCallsSectionProps {
  tool_calls_data: ToolCallEntry[];
}

export default function ToolCallsSection({
  tool_calls_data,
}: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedCalls, setExpandedCalls] = useState<Set<number>>(new Set());
  const { integrations } = useIntegrations();

  // Create a lookup map for custom integrations by id
  const integrationLookup = useMemo(() => {
    const lookup = new Map<string, { iconUrl?: string; name?: string }>();
    for (const int of integrations) {
      if (int.id) {
        lookup.set(int.id, {
          iconUrl: int.iconUrl,
          name: int.name,
        });
      }
    }
    return lookup;
  }, [integrations]);

  // Helper to get icon_url with fallback to integrations lookup
  const getIconUrl = (call: ToolCallEntry): string | undefined => {
    if (call.icon_url) return call.icon_url;
    // Fallback: look up from integrations if tool_category is a custom integration
    const integration = integrationLookup.get(call.tool_category);
    return integration?.iconUrl;
  };

  // Helper to get integration_name with fallback to integrations lookup
  const getIntegrationName = (call: ToolCallEntry): string | undefined => {
    if (call.integration_name) return call.integration_name;
    // Fallback: look up from integrations if tool_category is a custom integration
    const integration = integrationLookup.get(call.tool_category);
    return integration?.name;
  };

  const toggleCallExpansion = (index: number) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);

      return next;
    });
  };

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
      <div className="flex min-h-8 items-center -space-x-2">
        {displayIcons.map((call, index) => {
          const IconComponent = getToolCategoryIcon(
            call.tool_category || "general",
            {
              width: 21,
              height: 21,
            },
            getIconUrl(call),
          ) || (
            <div className="p-1 bg-zinc-800 rounded-lg text-zinc-400 backdrop-blur">
              <ToolsIcon width={21} height={21} />
            </div>
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
        {uniqueIcons.length > SHOWICONS && (
          <div className="z-0 flex size-7 min-h-7 min-w-7 items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500 font-normal">
            +{uniqueIcons.length - SHOWICONS}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-fit max-w-140">
      <Accordion
        variant="light"
        isCompact
        hideIndicator
        selectedKeys={isExpanded ? ["tools"] : []}
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
            <div className="flex items-center gap-2 hover:text-white text-zinc-500">
              {renderStackedIcons()}
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
          <div className="space-y-0">
            {tool_calls_data.map((call, index) => {
              const hasCategoryText =
                call.show_category !== false &&
                call.tool_category &&
                call.tool_category !== "unknown";
              const hasDetails = call.inputs || call.output;
              const isCallExpanded = expandedCalls.has(index);

              return (
                <div
                  key={`${call.tool_name}-step-${index}`}
                  className="flex items-stretch gap-2"
                >
                  <div className="flex flex-col items-center self-stretch">
                    <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
                      {getToolCategoryIcon(
                        call.tool_category || "general",
                        {
                          size: 21,
                          width: 21,
                          height: 21,
                        },
                        getIconUrl(call),
                      ) || (
                        <div className="p-1 bg-zinc-800 rounded-lg">
                          <ToolsIcon width={21} height={21} />
                        </div>
                      )}
                    </div>
                    {index < tool_calls_data.length - 1 && (
                      <div className="w-px flex-1 bg-default-200 min-h-4" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <button
                      type="button"
                      className={`flex items-center gap-1 group/parent ${hasDetails ? "cursor-pointer" : ""}  ${!hasCategoryText ? "pt-2" : ""}`}
                      onClick={() => hasDetails && toggleCallExpansion(index)}
                    >
                      <p
                        className={`text-xs text-zinc-400 font-medium ${hasDetails ? "group-hover/parent:text-white " : ""}`}
                      >
                        {call.message || formatToolName(call.tool_name)}
                      </p>
                      {hasDetails && (
                        <ChevronDown
                          className={`text-zinc-500 transition-transform ${isCallExpanded ? "rotate-180" : ""}`}
                          width={14}
                          height={14}
                        />
                      )}
                    </button>
                    {hasCategoryText && (
                      <p className="text-[11px] text-default-400 capitalize">
                        {getIntegrationName(call) ||
                          call.tool_category
                            .replace(/_/g, " ")
                            .split(" ")
                            .map(
                              (word) =>
                                word.charAt(0).toUpperCase() +
                                word.slice(1).toLowerCase(),
                            )
                            .join(" ")}
                      </p>
                    )}

                    {isCallExpanded && hasDetails && (
                      <div className="mt-2 space-y-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 mb-3 w-fit ">
                        {call.inputs && Object.keys(call.inputs).length > 0 && (
                          <div className="flex flex-col">
                            <span className="text-zinc-500 font-medium mb-1">
                              Input
                            </span>
                            <CompactMarkdown content={call.inputs} />
                          </div>
                        )}
                        {call.output && (
                          <div className="flex flex-col">
                            <span className="text-zinc-500 font-medium mb-1">
                              Output
                            </span>
                            <CompactMarkdown content={call.output} />
                          </div>
                        )}
                      </div>
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
