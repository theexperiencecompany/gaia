"use client";

import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  useDisclosure,
} from "@heroui/modal";
import { Button } from "@heroui/react";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { MessageMultiple02Icon } from "@/components/shared/icons";
import { getLinkByLabel } from "@/config/appConfig";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { chatApi } from "@/features/chat/api/chatApi";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import AddGoalDialog from "@/features/goals/components/AddGoalDialog";
import { useGoals } from "@/features/goals/hooks/useGoals";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { ContactSupportModal } from "@/features/support";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import CreateWorkflowModal from "@/features/workflows/components/CreateWorkflowModal";
import { useDeleteConversation } from "@/hooks/useDeleteConversation";
import { usePlatform } from "@/hooks/ui/usePlatform";

import { ComprehensiveSearchResponse, searchApi } from "../api/searchApi";
import {
  ANIMATION_CONFIG,
  COMMAND_MENU_STYLES,
  MENU_SECTIONS,
  MenuItemConfig,
} from "../config/commandMenuConfig";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Action handler type for clean code
type ActionHandler = () => void;
type ActionRegistry = Record<string, ActionHandler>;

export default function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { modifierKeyName } = usePlatform();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { logout } = useLogout();
  const { clearUser } = useUserActions();
  const fetchConversations = useFetchConversations();
  const deleteConversation = useDeleteConversation();
  const { createGoal } = useGoals();
  const { createTodo } = useTodoData({ autoLoad: false });

  // State
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] =
    useState<ComprehensiveSearchResponse>({
      conversations: [],
      messages: [],
      notes: [],
    });
  const [isSearching, setIsSearching] = useState(false);

  // Modal states
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [chatName, setChatName] = useState("");
  const {
    isOpen: workflowModalOpen,
    onOpen: openWorkflowModal,
    onClose: closeWorkflowModal,
  } = useDisclosure();
  const [goalDialogOpen, setGoalDialogOpen] = useState(false);
  const [todoModalOpen, setTodoModalOpen] = useState(false);

  // Reset and focus
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setSearch("");
      setSearchResults({ conversations: [], messages: [], notes: [] });
    }
  }, [open]);

  // Get current chat ID from pathname
  const getCurrentChatId = (): string | null => {
    if (pathname.startsWith("/c/")) {
      return pathname.split("/c/")[1] || null;
    }
    return null;
  };

  // Search with debouncing
  const handleSearch = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults({ conversations: [], messages: [], notes: [] });
      return;
    }

    setIsSearching(true);
    try {
      const response = await searchApi.search(query);
      setSearchResults(response);
    } catch (error) {
      console.error("Error fetching search results:", error);
      setSearchResults({ conversations: [], messages: [], notes: [] });
    } finally {
      setIsSearching(false);
    }
  }, []);

  useEffect(() => {
    const delayDebounceFn = setTimeout(() => handleSearch(search), 300);
    return () => clearTimeout(delayDebounceFn);
  }, [search, handleSearch]);

  // Keyboard shortcuts
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }
      if (open && e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      }
      if (open && e.key === "," && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        router.push("/settings");
        onOpenChange(false);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [open, onOpenChange, router]);

  // Clean action handlers using registry pattern
  const actionHandlers: ActionRegistry = {
    new_chat: () => {
      router.push("/c");
      onOpenChange(false);
    },

    star_chat: async () => {
      const chatId = getCurrentChatId();
      if (!chatId) {
        toast.error("Open a chat first to star it");
        return;
      }
      try {
        // Get current conversation to check star status
        await chatApi.toggleStarConversation(chatId, true);
        await fetchConversations();
        toast.success("Chat starred");
        onOpenChange(false);
      } catch (error) {
        console.error("Failed to star chat:", error);
      }
    },

    rename_chat: () => {
      const chatId = getCurrentChatId();
      if (!chatId) {
        toast.error("Open a chat first to rename it");
        return;
      }
      onOpenChange(false);
      setRenameModalOpen(true);
    },

    delete_chat: () => {
      const chatId = getCurrentChatId();
      if (!chatId) {
        toast.error("Open a chat first to delete it");
        return;
      }
      onOpenChange(false);
      setDeleteModalOpen(true);
    },

    create_calendar_event: () => {
      router.push("/calendar");
      onOpenChange(false);
    },

    send_email: () => {
      router.push("/mail");
      onOpenChange(false);
    },

    create_workflow: () => {
      onOpenChange(false);
      openWorkflowModal();
    },

    create_goal: () => {
      onOpenChange(false);
      setGoalDialogOpen(true);
    },

    create_todo: () => {
      onOpenChange(false);
      setTodoModalOpen(true);
    },

    log_out: async () => {
      try {
        onOpenChange(false);
        await logout();
        clearUser();
        router.push("/");
      } catch (error) {
        console.error("Error during logout:", error);
      }
    },

    create_support: () => {
      onOpenChange(false);
      setSupportModalOpen(true);
    },

    send_feedback: () => {
      onOpenChange(false);
      setSupportModalOpen(true);
    },

    help: () => {
      window.open("https://docs.heygaia.io", "_blank");
      onOpenChange(false);
    },
  };

  // Build menu items using action registry
  const buildMenuItem = useCallback(
    (config: MenuItemConfig): MenuItemConfig & { onSelect: () => void } => {
      // Handle actions from registry
      if (config.action && actionHandlers[config.action]) {
        return { ...config, onSelect: actionHandlers[config.action] };
      }

      // Handle external URLs
      if (config.externalUrl) {
        return {
          ...config,
          onSelect: () => {
            if (config.externalUrl === "discord") {
              const link = getLinkByLabel("Discord");
              window.open(link?.href || "https://discord.heygaia.io", "_blank");
            } else if (config.externalUrl === "whatsapp") {
              const link = getLinkByLabel("WhatsApp");
              window.open(
                link?.href || "https://whatsapp.heygaia.io",
                "_blank",
              );
            } else {
              window.open(config.externalUrl, "_blank");
            }
            onOpenChange(false);
          },
        };
      }

      // Handle navigation
      if (config.path) {
        return {
          ...config,
          onSelect: () => {
            router.push(config.path!);
            onOpenChange(false);
          },
        };
      }

      // Fallback
      return { ...config, onSelect: () => {} };
    },
    [actionHandlers, router, onOpenChange],
  );

  // Get filtered menu sections
  const getMenuSections = useCallback(() => {
    return MENU_SECTIONS.map((section) => ({
      ...section,
      items: section.items
        .filter((item) => {
          // Filter out upgrade if subscribed
          if (item.hideWhenSubscribed && subscriptionStatus?.is_subscribed) {
            return false;
          }
          // Filter by search
          if (search) {
            return item.label.toLowerCase().includes(search.toLowerCase());
          }
          return true;
        })
        .map(buildMenuItem),
    })).filter((section) => section.items.length > 0);
  }, [search, subscriptionStatus, buildMenuItem]);

  const menuSections = getMenuSections();

  return (
    <AnimatePresence>
      {open && (
        <div className={COMMAND_MENU_STYLES.modalWrapper}>
          {/* Backdrop */}
          <motion.div
            {...ANIMATION_CONFIG.backdrop}
            className={COMMAND_MENU_STYLES.backdrop}
            onClick={() => onOpenChange(false)}
          />

          {/* Command Menu */}
          <motion.div
            {...ANIMATION_CONFIG.container}
            className={COMMAND_MENU_STYLES.container}
          >
            <Command
              shouldFilter={false}
              loop
              className={COMMAND_MENU_STYLES.groupHeadings}
            >
              {/* Input */}
              <div className={COMMAND_MENU_STYLES.inputWrapper}>
                <Search className={COMMAND_MENU_STYLES.searchIcon} />
                <Command.Input
                  ref={inputRef}
                  value={search}
                  onValueChange={setSearch}
                  placeholder="Search or run a command..."
                  className={COMMAND_MENU_STYLES.input}
                />
                <Kbd keys={[modifierKeyName]}> K</Kbd>
              </div>

              <Command.List ref={listRef} className={COMMAND_MENU_STYLES.list}>
                <Command.Empty className={COMMAND_MENU_STYLES.empty}>
                  {isSearching ? "Searching..." : "No results found."}
                </Command.Empty>

                {/* Search Results */}
                {search && (
                  <>
                    {searchResults.conversations.length > 0 && (
                      <Command.Group heading="Conversations">
                        {searchResults.conversations
                          .slice(0, 3)
                          .map((conversation, index) => (
                            <Command.Item
                              key={`conversation-${index}`}
                              value={conversation.description || "Conversation"}
                              onSelect={() => {
                                router.push(
                                  `/c/${conversation.conversation_id}`,
                                );
                                onOpenChange(false);
                              }}
                              className={COMMAND_MENU_STYLES.item}
                            >
                              <MessageMultiple02Icon
                                width={16}
                                height={16}
                                color={undefined}
                              />
                              <div
                                className={COMMAND_MENU_STYLES.contentWrapper}
                              >
                                <div
                                  className={COMMAND_MENU_STYLES.resultTitle}
                                >
                                  {conversation.description || "Conversation"}
                                </div>
                                <div
                                  className={COMMAND_MENU_STYLES.resultSubtitle}
                                >
                                  Conversation
                                </div>
                              </div>
                            </Command.Item>
                          ))}
                      </Command.Group>
                    )}

                    {searchResults.messages.length > 0 && (
                      <Command.Group heading="Messages">
                        {searchResults.messages
                          .slice(0, 3)
                          .map((message, index) => (
                            <Command.Item
                              key={`message-${index}`}
                              value={message.snippet}
                              onSelect={() => {
                                router.push(`/c/${message.conversation_id}`);
                                onOpenChange(false);
                              }}
                              className={COMMAND_MENU_STYLES.item}
                            >
                              <Search
                                width={16}
                                height={16}
                                color={undefined}
                              />
                              <div
                                className={COMMAND_MENU_STYLES.contentWrapper}
                              >
                                <div
                                  className={
                                    COMMAND_MENU_STYLES.resultTitleClamp
                                  }
                                >
                                  {message.snippet}
                                </div>
                                <div
                                  className={COMMAND_MENU_STYLES.resultSubtitle}
                                >
                                  {new Date(
                                    message.message.date,
                                  ).toLocaleDateString()}
                                </div>
                              </div>
                            </Command.Item>
                          ))}
                      </Command.Group>
                    )}

                    <Command.Separator
                      className={COMMAND_MENU_STYLES.separator}
                    />
                  </>
                )}

                {/* Menu Sections */}
                {menuSections.map((section, sectionIndex) => (
                  <React.Fragment key={section.key}>
                    {sectionIndex > 0 && !search && (
                      <Command.Separator
                        className={COMMAND_MENU_STYLES.separator}
                      />
                    )}
                    <Command.Group
                      heading={section.heading}
                      className="pt-1! pb-3!"
                      style={{ padding: 0 }}
                    >
                      {section.items.map((item) => (
                        <Command.Item
                          key={item.id}
                          value={item.label}
                          onSelect={item.onSelect}
                          className={COMMAND_MENU_STYLES.item}
                        >
                          {item.icon}
                          <span className={COMMAND_MENU_STYLES.flexOne}>
                            {item.label}
                          </span>
                          {item.shortcut && (
                            <kbd className={COMMAND_MENU_STYLES.itemShortcut}>
                              {item.shortcut}
                            </kbd>
                          )}
                        </Command.Item>
                      ))}
                    </Command.Group>
                  </React.Fragment>
                ))}
              </Command.List>

              {/* Footer */}
              <div className={COMMAND_MENU_STYLES.footer}>
                <p className={COMMAND_MENU_STYLES.footerText}>
                  Type to search, use ↑↓ to navigate, ↵ to select, ESC to close
                </p>
              </div>
            </Command>
          </motion.div>
        </div>
      )}

      {/* Support Modal */}
      <ContactSupportModal
        open={supportModalOpen}
        onOpenChange={setSupportModalOpen}
      />

      {/* Rename Chat Modal */}
      <Modal
        isOpen={renameModalOpen}
        onOpenChange={setRenameModalOpen}
        className="text-foreground dark"
      >
        <ModalContent>
          <ModalHeader>Rename Chat</ModalHeader>
          <ModalBody>
            <Input
              autoFocus
              label="Chat Name"
              value={chatName}
              onChange={(e) => setChatName(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === "Enter" && chatName.trim()) {
                  const chatId = getCurrentChatId();
                  if (chatId) {
                    try {
                      await chatApi.renameConversation(chatId, chatName);
                      await fetchConversations(1, 20, false);
                      setRenameModalOpen(false);
                      setChatName("");
                      toast.success("Chat renamed");
                    } catch (error) {
                      console.error("Failed to rename chat:", error);
                    }
                  }
                }
              }}
            />
          </ModalBody>
          <ModalFooter>
            <Button
              variant="light"
              onPress={() => {
                setRenameModalOpen(false);
                setChatName("");
              }}
            >
              Cancel
            </Button>
            <Button
              color="primary"
              onPress={async () => {
                const chatId = getCurrentChatId();
                if (chatId && chatName.trim()) {
                  try {
                    await chatApi.renameConversation(chatId, chatName);
                    await fetchConversations(1, 20, false);
                    setRenameModalOpen(false);
                    setChatName("");
                    toast.success("Chat renamed");
                  } catch (error) {
                    console.error("Failed to rename chat:", error);
                  }
                }
              }}
            >
              Rename
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {/* Delete Chat Modal */}
      <Modal
        isOpen={deleteModalOpen}
        onOpenChange={setDeleteModalOpen}
        className="text-foreground dark"
      >
        <ModalContent>
          <ModalHeader>Delete Chat</ModalHeader>
          <ModalBody>
            <p>
              Are you sure you want to delete this chat? This action cannot be
              undone.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="light" onPress={() => setDeleteModalOpen(false)}>
              Cancel
            </Button>
            <Button
              color="danger"
              onPress={async () => {
                const chatId = getCurrentChatId();
                if (chatId) {
                  try {
                    router.push("/c");
                    await deleteConversation(chatId);
                    await fetchConversations(1, 20, false);
                    setDeleteModalOpen(false);
                    toast.success("Chat deleted");
                  } catch (error) {
                    console.error("Failed to delete chat:", error);
                  }
                }
              }}
            >
              Delete
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {/* Workflow Creation Modal */}
      <CreateWorkflowModal
        isOpen={workflowModalOpen}
        onClose={closeWorkflowModal}
        onSuccess={() => {
          closeWorkflowModal();
          router.push("/workflows");
        }}
      />

      {/* Goal Creation Dialog */}
      <AddGoalDialog
        openDialog={goalDialogOpen}
        setOpenDialog={setGoalDialogOpen}
        addGoal={async (goalTitle) => {
          try {
            const newGoal = await createGoal({ title: goalTitle });
            router.push(`/goals/${newGoal.id}`);
          } catch (err) {
            console.error(err);
          }
        }}
      />

      {/* Todo Creation - using redirect to page with modal */}
      {todoModalOpen && (
        <Modal
          isOpen={todoModalOpen}
          onOpenChange={setTodoModalOpen}
          className="text-foreground dark"
        >
          <ModalContent>
            <ModalHeader>Create Todo</ModalHeader>
            <ModalBody>
              <Input
                autoFocus
                label="Todo Title"
                placeholder="What needs to be done?"
                onKeyDown={async (e) => {
                  if (e.key === "Enter") {
                    const title = (e.target as HTMLInputElement).value.trim();
                    if (title) {
                      try {
                        await createTodo({ title });
                        setTodoModalOpen(false);
                        router.push("/todos");
                        toast.success("Todo created");
                      } catch (error) {
                        console.error("Failed to create todo:", error);
                      }
                    }
                  }
                }}
              />
            </ModalBody>
            <ModalFooter>
              <Button variant="light" onPress={() => setTodoModalOpen(false)}>
                Cancel
              </Button>
              <Button
                color="primary"
                onPress={() => {
                  setTodoModalOpen(false);
                  router.push("/todos");
                }}
              >
                Open Todos
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>
      )}
    </AnimatePresence>
  );
}
