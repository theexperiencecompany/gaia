"use client";

import { Kbd } from "@heroui/kbd";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useRef, useState } from "react";

import { MessageMultiple02Icon } from "@/components/shared/icons";
import { getLinkByLabel } from "@/config/appConfig";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
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
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setSearch("");
      setSearchResults({ conversations: [], messages: [], notes: [] });
    }
  }, [open]);

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
      // Command+K to toggle
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }

      // ESC to close
      if (open && e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      }

      // Command+, for settings
      if (open && e.key === "," && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        router.push("/settings");
        onOpenChange(false);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [open, onOpenChange, router]);

  // Action handlers
  const handleNewChat = useCallback(() => {
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
      return { ...config, onSelect: () => {} };
    },
    [handleNewChat, router, onOpenChange],
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
    </AnimatePresence>
  );
}
