import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { AnimatePresence, motion } from "framer-motion";
import type React from "react";
import { useMemo, useState } from "react";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { Cancel01Icon, GridIcon, SearchIcon, Tick02Icon } from "@/icons";

import { dummyIntegrations } from "./constants";

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

// Dummy data matching the complete tool registry from backend
const dummyTools = {
  tools: [
    // SearchIcon tools (core)
    {
      name: "web_search_tool",
      category: "search",
      required_integration: null,
    },
    {
      name: "fetch_webpages",
      category: "search",
      required_integration: null,
    },
    // Documents tools (core)
    {
      name: "query_file",
      category: "documents",
      required_integration: null,
    },
    {
      name: "generate_document",
      category: "documents",
      required_integration: null,
    },
    // Notifications tools
    {
      name: "get_notifications",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "search_notifications",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "get_notification_count",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "mark_notifications_read",
      category: "notifications",
      required_integration: null,
    },
    // Productivity tools (todos + reminders)
    {
      name: "create_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "search_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "semantic_search_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_todo_statistics",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_today_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_upcoming_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "create_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_projects",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_todos_by_label",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_all_labels",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_complete_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_move_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_delete_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "add_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "create_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_user_reminders_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "search_reminders_tool",
      category: "productivity",
      required_integration: null,
    },
    // Goal tracking tools
    {
      name: "create_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "list_goals",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "get_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "delete_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "generate_roadmap",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "update_goal_node",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "search_goals",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "get_goal_statistics",
      category: "goal_tracking",
      required_integration: null,
    },
    // Support tools
    {
      name: "create_support_ticket",
      category: "support",
      required_integration: null,
    },
    // Memory tools
    {
      name: "add_memory",
      category: "memory",
      required_integration: null,
    },
    {
      name: "search_memory",
      category: "memory",
      required_integration: null,
    },
    // Development tools
    {
      name: "execute_code",
      category: "development",
      required_integration: null,
    },
    {
      name: "create_flowchart",
      category: "development",
      required_integration: null,
    },
    // Creative tools
    {
      name: "generate_image",
      category: "creative",
      required_integration: null,
    },
    // Weather tools
    {
      name: "get_weather",
      category: "weather",
      required_integration: null,
    },
    // Calendar tools (requires integration)
    {
      name: "fetch_calendar_list",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "create_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "edit_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "fetch_calendar_events",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "search_calendar_events",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "view_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "delete_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    // Google Docs tools (requires integration)
    {
      name: "create_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "list_google_docs_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "get_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "update_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "format_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "share_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "search_google_docs_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    // Gmail tools (requires integration - delegated)
    {
      name: "gmail_search_emails",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_get_profile",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_create_email_draft",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_send_email",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_fetch_emails",
      category: "gmail",
      required_integration: "gmail",
    },
    // Notion tools (requires integration - delegated)
    {
      name: "notion_create_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_get_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_find_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_update_page",
      category: "notion",
      required_integration: "notion",
    },
    // Twitter tools (requires integration - delegated)
    {
      name: "twitter_post_tweet",
      category: "twitter",
      required_integration: "twitter",
    },
    {
      name: "twitter_get_user_tweets",
      category: "twitter",
      required_integration: "twitter",
    },
    {
      name: "twitter_search_tweets",
      category: "twitter",
      required_integration: "twitter",
    },
    // LinkedIn tools (requires integration - delegated)
    {
      name: "linkedin_post_content",
      category: "linkedin",
      required_integration: "linkedin",
    },
    {
      name: "linkedin_get_profile",
      category: "linkedin",
      required_integration: "linkedin",
    },
    // Google Sheets tools (requires integration - delegated)
    {
      name: "google_sheets_create_spreadsheet",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
    {
      name: "google_sheets_get_values",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
    {
      name: "google_sheets_update_values",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
  ],
  total_count: 109,
  categories: [
    "calendar",
    "creative",
    "development",
    "documents",
    "gmail",
    "goal_tracking",
    "googledocs",
    "googlesheets",
    "linkedin",
    "memory",
    "notifications",
    "notion",
    "productivity",
    "search",
    "support",
    "twitter",
    "weather",
  ],
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
        <motion.div
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
          style={{ height: "min(50vh, 280px)" }}
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
          <motion.div
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
          </motion.div>

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
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default DummySlashCommandDropdown;
