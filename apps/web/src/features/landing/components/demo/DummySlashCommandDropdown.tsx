import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Cancel01Icon, GridIcon, SearchIcon, Tick02Icon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import type React from "react";
import { useMemo, useState } from "react";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

import { dummyIntegrations, dummyTools } from "./constants";

// Dummy Integrations Card Component
const DummyIntegrationsCard: React.FC = () => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="mx-2 mb-3 border-b-1 border-zinc-800">
      <Accordion
        variant="light"
        isCompact
        selectedKeys={isExpanded ? new Set(["integrations"]) : new Set([])}
        onSelectionChange={(keys) => {
          const expanded =
            keys === "all" || (keys instanceof Set && keys.has("integrations"));
          setIsExpanded(expanded);
        }}
        itemClasses={{
          base: "pb-1",
          trigger: "cursor-pointer",
        }}
      >
        <AccordionItem
          key="integrations"
          title={
            <div className="flex items-center gap-3 px-1 pt-1">
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-normal text-foreground-500">
                    Integrations
                  </span>
                  <span className="text-xs font-light text-zinc-400">
                    {dummyIntegrations.length}/{dummyIntegrations.length}
                  </span>
                </div>
              </div>
            </div>
          }
        >
          <div onClick={(e) => e.stopPropagation()}>
            <div className="grid grid-cols-2 gap-2">
              {dummyIntegrations.map((integration) => (
                <div
                  key={integration.id}
                  className="flex items-center gap-2 rounded-lg p-2 px-3"
                >
                  {/* Icon */}
                  <div className="flex-shrink-0">
                    <div className="flex items-center justify-center rounded-lg">
                      {getToolCategoryIcon(integration.id, {
                        size: 25,
                        width: 25,
                        height: 25,
                        showBackground: false,
                      })}
                    </div>
                  </div>

                  {/* Name */}
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-xs text-zinc-300">
                      {integration.name}
                    </span>
                  </div>

                  {/* Status */}
                  <div className="flex-shrink-0">
                    <Chip size="sm" variant="flat" color="success">
                      Connected
                    </Chip>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
};

interface DummySlashCommandDropdownProps {
  isVisible: boolean;
  onClose: () => void;
  openedViaButton?: boolean;
}

const DummySlashCommandDropdown: React.FC<DummySlashCommandDropdownProps> = ({
  isVisible,
  onClose,
  openedViaButton = false,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const categories = useMemo(() => {
    return ["all", ...dummyTools.categories.sort()];
  }, []);

  const filteredTools = useMemo(() => {
    let filtered = dummyTools.tools;

    if (selectedCategory !== "all") {
      filtered = filtered.filter((tool) => tool.category === selectedCategory);
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (tool) =>
          formatToolName(tool.name).toLowerCase().includes(query) ||
          tool.category.toLowerCase().includes(query),
      );
    }

    return filtered;
  }, [selectedCategory, searchQuery]);

  const handleToolClick = (toolName: string) => {
    // Do nothing - this is a dummy component
    console.log(`Clicked tool: ${toolName}`);
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <m.div
          initial={{ opacity: 0, y: -8, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.95 }}
          transition={{
            type: "spring",
            damping: 20,
            stiffness: 300,
            duration: 0.15,
          }}
          className="relative z-[200] mx-auto flex w-full flex-col overflow-hidden rounded-3xl border-1 border-zinc-700 bg-zinc-900/60 shadow-2xl backdrop-blur-2xl"
          style={{ height: "min(60vh, 420px)" }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header section - Only show when opened via button */}
          {openedViaButton && (
            <div className="flex items-center gap-2 p-3">
              <div className="flex-1">
                <Input
                  type="text"
                  placeholder="Search tools..."
                  value={searchQuery}
                  size="sm"
                  radius="full"
                  startContent={<SearchIcon size={16} />}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                />
              </div>
              <Button
                onPress={onClose}
                isIconOnly
                size="sm"
                radius="full"
                variant="flat"
                aria-label="Close button dummy composer"
              >
                <Cancel01Icon size={14} />
              </Button>
            </div>
          )}

          {/* Category Tabs */}
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
          >
            <ScrollShadow orientation="horizontal" className="overflow-x-auto">
              <div className="flex min-w-max gap-1 px-2 py-2">
                {categories.map((category) => (
                  <button
                    type="button"
                    key={category}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedCategory(category);
                    }}
                    className={`flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all ${
                      selectedCategory === category
                        ? "bg-zinc-700 text-white"
                        : "text-zinc-400 hover:bg-white/10 hover:text-zinc-300"
                    }`}
                  >
                    {category === "all" ? (
                      <GridIcon
                        size={16}
                        strokeWidth={2}
                        className="text-gray-400"
                      />
                    ) : (
                      getToolCategoryIcon(category)
                    )}
                    <span className="capitalize">
                      {category === "all" ? "All" : category.replace("_", " ")}
                    </span>
                  </button>
                ))}
              </div>
            </ScrollShadow>
          </m.div>

          {/* Tool List */}
          <div className="flex-1 overflow-y-auto">
            <div className="py-2">
              {/* Integrations Card - Only show in "all" category and when not filtering */}
              {selectedCategory === "all" && !searchQuery.trim() && (
                <DummyIntegrationsCard />
              )}

              {filteredTools.map((tool) => (
                <div
                  key={tool.name}
                  className="relative mx-2 mb-1 cursor-pointer rounded-xl border border-transparent transition-all duration-150 hover:border-zinc-600 hover:bg-white/5"
                  onClick={() => handleToolClick(tool.name)}
                >
                  <div className="flex items-center gap-3 p-3">
                    <div className="flex-shrink-0">
                      {getToolCategoryIcon(tool.category)}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm text-foreground-600">
                          {formatToolName(tool.name)}
                        </span>
                        <div className="flex items-center gap-2">
                          {selectedCategory === "all" && (
                            <span className="rounded-full bg-zinc-600 px-2 py-0.5 text-xs text-zinc-200 capitalize">
                              {tool.category.replace("_", " ")}
                            </span>
                          )}
                          {tool.required_integration && (
                            <div className="flex items-center gap-1">
                              <Tick02Icon className="h-3 w-3 text-green-400" />
                              <span className="text-xs text-green-400">
                                Connected
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </m.div>
      )}
    </AnimatePresence>
  );
};

export default DummySlashCommandDropdown;
