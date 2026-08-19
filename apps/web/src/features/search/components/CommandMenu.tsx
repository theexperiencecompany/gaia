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

function CommandInputRow({
  inputRef,
  search,
  onSearchChange,
  modifierKeyName,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  search: string;
  onSearchChange: (value: string) => void;
  modifierKeyName: "command" | "ctrl";
}) {
  return (
    <div className={COMMAND_MENU_STYLES.inputWrapper}>
      <SearchIcon className={COMMAND_MENU_STYLES.searchIcon} />
      <Command.Input
        ref={inputRef}
        value={search}
        onValueChange={onSearchChange}
        placeholder="Search or run a command..."
        className={COMMAND_MENU_STYLES.input}
      />
      <Kbd keys={[modifierKeyName]}> K</Kbd>
    </div>
  );
}

function ConversationsGroup({
  conversations,
  onSelect,
}: {
  conversations: ComprehensiveSearchResponse["conversations"];
  onSelect: (conversationId: string) => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <Command.Group heading="Conversations">
      {conversations.slice(0, 3).map((conversation) => (
        <Command.Item
          key={`conversation-${conversation.conversation_id}`}
          value={conversation.description || "Conversation"}
          onSelect={() => onSelect(conversation.conversation_id)}
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

function MessagesGroup({
  messages,
  onSelect,
}: {
  messages: ComprehensiveSearchResponse["messages"];
  onSelect: (conversationId: string, messageId: string) => void;
}) {
  if (messages.length === 0) return null;
  return (
    <Command.Group heading="Messages">
      {messages.slice(0, 3).map((message) => (
        <Command.Item
          key={`message-${message.message.message_id}`}
          value={message.snippet}
          onSelect={() =>
            onSelect(message.conversation_id, message.message.message_id)
          }
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

function SearchResultsSection({
  search,
  searchResults,
  onSelectConversation,
  onSelectMessage,
}: {
  search: string;
  searchResults: ComprehensiveSearchResponse;
  onSelectConversation: (id: string) => void;
  onSelectMessage: (conversationId: string, messageId: string) => void;
}) {
  if (!search) return null;
  return (
    <>
      <ConversationsGroup
        conversations={searchResults.conversations}
        onSelect={onSelectConversation}
      />
      <MessagesGroup
        messages={searchResults.messages}
        onSelect={onSelectMessage}
      />
      <Command.Separator className={COMMAND_MENU_STYLES.separator} />
    </>
  );
}

function MenuSectionsList({
  sections,
  search,
}: {
  sections: Array<
    Omit<MenuSectionConfig, "items"> & {
      items: (MenuItemConfig & { onSelect: () => void })[];
    }
  >;
  search: string;
}) {
  return (
    <>
      {sections.map((section, sectionIndex) => (
        <React.Fragment key={section.key}>
          {sectionIndex > 0 && !search && (
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

function CommandFooter() {
  return (
    <div className={COMMAND_MENU_STYLES.footer}>
      <p className={COMMAND_MENU_STYLES.footerText}>
        Type to search, use ↑↓ to navigate, ↵ to select, ESC to close
      </p>
    </div>
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
    if (open) {
      trackEvent(ANALYTICS_EVENTS.SEARCH_GLOBAL_OPENED);
      const focusTimer = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(focusTimer);
    }
    setSearch("");
    setSearchResults({ conversations: [], messages: [], notes: [] });
    return undefined;
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

  // Keep the refs current outside the render body — render must stay pure.
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

  // Get filtered menu sections
  const menuSections = useMemo(() => {
    const sections: Array<
      Omit<MenuSectionConfig, "items"> & {
        items: (MenuItemConfig & { onSelect: () => void })[];
      }
    > = [];
    for (const section of MENU_SECTIONS) {
      const items: (MenuItemConfig & { onSelect: () => void })[] = [];
      for (const item of section.items) {
        // Filter out upgrade if subscribed
        if (item.hideWhenSubscribed && subscriptionStatus?.is_subscribed) {
          continue;
        }
        // Filter by search
        if (search) {
          if (!item.label.toLowerCase().includes(search.toLowerCase())) {
            continue;
          }
        }
        items.push(buildMenuItem(item));
      }
      if (items.length === 0) continue;
      sections.push({ ...section, items });
    }
    return sections;
  }, [search, subscriptionStatus, buildMenuItem]);

  const handleSelectConversation = useCallback(
    (conversationId: string) => {
      trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
        result_type: "conversation",
        conversation_id: conversationId,
      });
      router.push(`/c/${conversationId}`);
      onOpenChange(false);
    },
    [router, onOpenChange],
  );

  const handleSelectMessage = useCallback(
    (conversationId: string, messageId: string) => {
      trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
        result_type: "message",
        conversation_id: conversationId,
        message_id: messageId,
      });
      router.push(`/c/${conversationId}`);
      onOpenChange(false);
    },
    [router, onOpenChange],
  );

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
              <CommandInputRow
                inputRef={inputRef}
                search={search}
                onSearchChange={setSearch}
                modifierKeyName={modifierKeyName}
              />

              <Command.List ref={listRef} className={COMMAND_MENU_STYLES.list}>
                <Command.Empty className={COMMAND_MENU_STYLES.empty}>
                  {isSearching ? "Searching..." : "No results found."}
                </Command.Empty>

                <SearchResultsSection
                  search={search}
                  searchResults={searchResults}
                  onSelectConversation={handleSelectConversation}
                  onSelectMessage={handleSelectMessage}
                />

                <MenuSectionsList sections={menuSections} search={search} />
              </Command.List>

              <CommandFooter />
            </Command>
          </m.div>
        </div>
      )}
    </AnimatePresence>
  );
}
