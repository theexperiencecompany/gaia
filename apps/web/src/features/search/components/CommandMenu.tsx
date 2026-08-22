"use client";

import { Kbd } from "@heroui/kbd";
import { MessageMultiple02Icon, SearchIcon } from "@icons";
import { Command } from "cmdk";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getLinkByLabel } from "@/config/appConfig";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import { type ComprehensiveSearchResponse, searchApi } from "../api/searchApi";
import {
  ANIMATION_CONFIG,
  COMMAND_MENU_STYLES,
  MENU_SECTIONS,
  type MenuItemConfig,
  type MenuSectionConfig,
} from "../config/commandMenuConfig";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type CommandMenuItem = MenuItemConfig & { onSelect: () => void };
type CommandMenuSection = Omit<MenuSectionConfig, "items"> & {
  items: CommandMenuItem[];
};

/** Deep-link search results for conversations, capped at 3 entries. */
function ConversationResults({
  conversations,
  onOpen,
}: Readonly<{
  conversations: ComprehensiveSearchResponse["conversations"];
  onOpen: (conversationId: string) => void;
}>) {
  if (conversations.length === 0) return null;
  return (
    <Command.Group heading="Conversations">
      {conversations.slice(0, 3).map((conversation) => (
        <Command.Item
          key={`conversation-${conversation.conversation_id}`}
          value={conversation.description || "Conversation"}
          onSelect={() => {
            trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
              result_type: "conversation",
              conversation_id: conversation.conversation_id,
            });
            onOpen(conversation.conversation_id);
          }}
          className={COMMAND_MENU_STYLES.item}
        >
          <MessageMultiple02Icon width={16} height={16} />
          <div className={COMMAND_MENU_STYLES.contentWrapper}>
            <div className={COMMAND_MENU_STYLES.resultTitle}>
              {conversation.description || "Conversation"}
            </div>
            <div className={COMMAND_MENU_STYLES.resultSubtitle}>
              Conversation
            </div>
          </div>
        </Command.Item>
      ))}
    </Command.Group>
  );
}

/** Deep-link search results for messages, capped at 3 entries. */
function MessageResults({
  messages,
  onOpen,
}: Readonly<{
  messages: ComprehensiveSearchResponse["messages"];
  onOpen: (conversationId: string) => void;
}>) {
  if (messages.length === 0) return null;
  return (
    <Command.Group heading="Messages">
      {messages.slice(0, 3).map((message) => (
        <Command.Item
          key={`message-${message.message.message_id}`}
          value={message.snippet}
          onSelect={() => {
            trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
              result_type: "message",
              conversation_id: message.conversation_id,
              message_id: message.message.message_id,
            });
            onOpen(message.conversation_id);
          }}
          className={COMMAND_MENU_STYLES.item}
        >
          <SearchIcon width={16} height={16} />
          <div className={COMMAND_MENU_STYLES.contentWrapper}>
            <div className={COMMAND_MENU_STYLES.resultTitleClamp}>
              {message.snippet}
            </div>
            <div
              className={COMMAND_MENU_STYLES.resultSubtitle}
              suppressHydrationWarning
            >
              {new Date(message.message.date).toLocaleDateString()}
            </div>
          </div>
        </Command.Item>
      ))}
    </Command.Group>
  );
}

/** The static (non-search) menu sections built from config. */
function MenuSectionsList({
  sections,
  showSeparators,
}: Readonly<{ sections: CommandMenuSection[]; showSeparators: boolean }>) {
  return (
    <>
      {sections.map((section, sectionIndex) => (
        <React.Fragment key={section.key}>
          {sectionIndex > 0 && showSeparators && (
            <Command.Separator className={COMMAND_MENU_STYLES.separator} />
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
    </>
  );
}

export default function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const router = useRouter();
  const { modifierKeyName } = usePlatform();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] =
    useState<ComprehensiveSearchResponse>({
      conversations: [],
      messages: [],
      notes: [],
    });
  const [isSearching, setIsSearching] = useState(false);

  // Reset and focus
  useEffect(() => {
    if (!open) {
      setSearch("");
      setSearchResults({ conversations: [], messages: [], notes: [] });
      return;
    }
    trackEvent(ANALYTICS_EVENTS.SEARCH_GLOBAL_OPENED);
    const focusTimer = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(focusTimer);
  }, [open]);

  // SearchIcon with debouncing
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

  const openRef = useRef(open);
  const onOpenChangeRef = useRef(onOpenChange);
  const routerRef = useRef(router);
  useEffect(() => {
    openRef.current = open;
    onOpenChangeRef.current = onOpenChange;
    routerRef.current = router;
  });

  // Keyboard shortcuts — registered once, reads latest values via refs
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const isOpen = openRef.current;
      const changeOpen = onOpenChangeRef.current;
      const nav = routerRef.current;

      // Command+K to toggle
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        changeOpen(!isOpen);
      }

      // ESC to close
      if (isOpen && e.key === "Escape") {
        e.preventDefault();
        changeOpen(false);
      }

      // Command+, for settings
      if (isOpen && e.key === "," && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        nav.push("/settings");
        changeOpen(false);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  // Action handlers
  const handleNewChat = useCallback(() => {
    prepareNewChat();
    router.push("/c");
    onOpenChange(false);
  }, [router, onOpenChange]);

  const openConversation = useCallback(
    (conversationId: string) => {
      router.push(`/c/${conversationId}`);
      onOpenChange(false);
    },
    [router, onOpenChange],
  );

  // Build menu items from config
  const buildMenuItem = useCallback(
    (config: MenuItemConfig): MenuItemConfig & { onSelect: () => void } => {
      // Handle special actions
      if (config.action === "new_chat") {
        return { ...config, onSelect: handleNewChat };
      }

      // Handle external URLs
      if (config.externalUrl) {
        return {
          ...config,
          onSelect: () => {
            const link = getLinkByLabel(
              config.externalUrl === "discord" ? "Discord" : "WhatsApp",
            );
            window.open(
              link?.href || `https://${config.externalUrl}.heygaia.io`,
              "_blank",
              "noopener,noreferrer",
            );
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
      return {
        ...config,
        onSelect: () => {
          /* fallback: item without a handler is inert */
        },
      };
    },
    [handleNewChat, router, onOpenChange],
  );

  // Get filtered menu sections — built in a single pass over sections/items
  const menuSections = useMemo(() => {
    const sections: CommandMenuSection[] = [];
    for (const section of MENU_SECTIONS) {
      const items: CommandMenuItem[] = [];
      for (const item of section.items) {
        // Filter out upgrade if subscribed
        if (item.hideWhenSubscribed && subscriptionStatus?.is_subscribed) {
          continue;
        }
        // Filter by search
        if (
          search &&
          !item.label.toLowerCase().includes(search.toLowerCase())
        ) {
          continue;
        }
        items.push(buildMenuItem(item));
      }
      if (items.length > 0) {
        sections.push({ ...section, items });
      }
    }
    return sections;
  }, [search, subscriptionStatus, buildMenuItem]);

  return (
    <AnimatePresence>
      {open && (
        <div className={COMMAND_MENU_STYLES.modalWrapper}>
          {/* Backdrop */}
          <m.div
            {...ANIMATION_CONFIG.backdrop}
            className={COMMAND_MENU_STYLES.backdrop}
            onClick={() => onOpenChange(false)}
          />

          {/* Command Menu */}
          <m.div
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
                <SearchIcon className={COMMAND_MENU_STYLES.searchIcon} />
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
                    <ConversationResults
                      conversations={searchResults.conversations}
                      onOpen={openConversation}
                    />

                    <MessageResults
                      messages={searchResults.messages}
                      onOpen={openConversation}
                    />

                    <Command.Separator
                      className={COMMAND_MENU_STYLES.separator}
                    />
                  </>
                )}

                {/* Menu Sections */}
                <MenuSectionsList
                  sections={menuSections}
                  showSeparators={!search}
                />
              </Command.List>

              {/* Footer */}
              <div className={COMMAND_MENU_STYLES.footer}>
                <p className={COMMAND_MENU_STYLES.footerText}>
                  Type to search, use ↑↓ to navigate, ↵ to select, ESC to close
                </p>
              </div>
            </Command>
          </m.div>
        </div>
      )}
    </AnimatePresence>
  );
}
