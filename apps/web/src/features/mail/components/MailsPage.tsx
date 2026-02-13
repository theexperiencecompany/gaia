"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Spinner } from "@heroui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";
import { Tooltip } from "@heroui/tooltip";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { mailApi } from "@/features/mail/api/mailApi";
import { EmailFrom } from "@/features/mail/components/MailFrom";
import { useEmailActions } from "@/features/mail/hooks/useEmailActions";
import { useEmailAnalysisIndicators } from "@/features/mail/hooks/useEmailAnalysis";
import { useEmailReadStatus } from "@/features/mail/hooks/useEmailReadStatus";
import { useEmailSelection } from "@/features/mail/hooks/useEmailSelection";
import { useEmailViewer } from "@/features/mail/hooks/useEmailViewer";
import { useMailTabs } from "@/features/mail/hooks/useMailTabs";
import { useTableInfiniteScroll } from "@/features/mail/hooks/useTableInfiniteScroll";
import { formatTime } from "@/features/mail/utils/mailUtils";
import {
  Archive01Icon,
  Cancel01Icon,
  CheckmarkSquare03Icon,
  Delete02Icon,
  SearchIcon,
  SparklesIcon,
  SquareIcon,
  StarIcon,
} from "@/icons";
import type { EmailData } from "@/types/features/mailTypes";

import { EmailHoverSummary } from "./EmailHoverSummary";
import { EmailTabs } from "./EmailTabs";
import { SelectionToolbar } from "./SelectionToolbar";
import ViewEmail from "./ViewMail";

function AIAnalysisIndicator({ hasAnalysis }: { hasAnalysis: boolean }) {
  if (!hasAnalysis) return null;
  return (
    <Tooltip content="AI Analysis Available" color="primary">
      <div className="flex items-center justify-center">
        <SparklesIcon
          width={16}
          height={16}
          color="#00bbff"
          fill="#00bbff"
          className="drop-shadow-md"
        />
      </div>
    </Tooltip>
  );
}

export default function MailsPage() {
  const { activeTab, setActiveTab } = useMailTabs();
  const { toggleReadStatus } = useEmailReadStatus(activeTab);
  const { toggleStarStatus, archiveEmail, trashEmail } =
    useEmailActions(activeTab);

  const {
    emails,
    isLoading,
    hasNextPage,
    bottomRef,
    error: emailsError,
  } = useTableInfiniteScroll(activeTab);

  const {
    selectedKeys,
    selectedCount,
    onSelectionChange,
    clearSelections,
    bulkMarkAsRead,
    bulkMarkAsUnread,
    bulkStarEmails,
    bulkUnstarEmails,
    bulkArchiveEmails,
    bulkTrashEmails,
  } = useEmailSelection(activeTab);

  const emailIds = useMemo(() => emails.map((email) => email.id), [emails]);

  const emailAnalysisIndicators = useEmailAnalysisIndicators(
    emailIds,
    emailIds.length > 0,
  );

  const {
    threadMessages,
    isLoadingThread,
    openEmail,
    closeEmail,
    selectedEmailId,
  } = useEmailViewer();

  // Search state (Task 30)
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Set<string> | null>(
    null,
  );
  const [isSearching, setIsSearching] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Keyboard-focused email index (Task 18)
  const [focusedIndex, setFocusedIndex] = useState(-1);

  const handleSearch = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        setSearchResults(null);
        setIsSearching(false);
        return;
      }
      setIsSearching(true);
      try {
        const result = await mailApi.searchEmails(query);
        if (result.emails) {
          setSearchResults(new Set(result.emails));
        } else {
          setSearchResults(new Set());
        }
      } catch {
        setSearchResults(null);
      } finally {
        setIsSearching(false);
      }
    },
    [],
  );

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchQuery(value);
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
      }
      searchTimerRef.current = setTimeout(() => {
        handleSearch(value);
      }, 300);
    },
    [handleSearch],
  );

  const clearSearch = useCallback(() => {
    setSearchQuery("");
    setSearchResults(null);
    setIsSearching(false);
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current);
    }
  }, []);

  const toggleSearch = useCallback(() => {
    if (isSearchOpen) {
      clearSearch();
      setIsSearchOpen(false);
    } else {
      setIsSearchOpen(true);
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [isSearchOpen, clearSearch]);

  // Filtered emails based on search results
  const filteredEmails = useMemo(() => {
    if (!searchResults) return emails;
    return emails.filter((email) => searchResults.has(email.id));
  }, [emails, searchResults]);

  const handleToggleReadStatus = (
    e: React.MouseEvent,
    email: EmailData,
  ) => {
    e.stopPropagation();
    toggleReadStatus(email);
  };

  const handleToggleStarStatus = (
    e: React.MouseEvent,
    email: EmailData,
  ) => {
    e.stopPropagation();
    toggleStarStatus(email);
  };

  const handleArchiveEmail = (
    e: React.MouseEvent,
    email: EmailData,
  ) => {
    e.stopPropagation();
    archiveEmail(email.id);
  };

  const handleTrashEmail = (
    e: React.MouseEvent,
    email: EmailData,
  ) => {
    e.stopPropagation();
    trashEmail(email.id);
  };

  // Keyboard shortcuts (Task 18)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Do not handle shortcuts when a modal is open
      if (selectedEmailId) return;

      // Do not handle shortcuts when typing in an input
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      switch (e.key) {
        case "j": {
          e.preventDefault();
          setFocusedIndex((prev) => {
            const next = prev + 1;
            return next < filteredEmails.length ? next : prev;
          });
          break;
        }
        case "k": {
          e.preventDefault();
          setFocusedIndex((prev) => {
            const next = prev - 1;
            return next >= 0 ? next : prev;
          });
          break;
        }
        case "x": {
          e.preventDefault();
          if (
            focusedIndex >= 0 &&
            focusedIndex < filteredEmails.length
          ) {
            const email = filteredEmails[focusedIndex];
            if (email) {
              const current =
                selectedKeys === "all"
                  ? new Set(
                      filteredEmails.map((em) => em.id),
                    )
                  : new Set(selectedKeys);
              if (current.has(email.id)) {
                current.delete(email.id);
              } else {
                current.add(email.id);
              }
              onSelectionChange(current);
            }
          }
          break;
        }
        case "e": {
          e.preventDefault();
          if (
            focusedIndex >= 0 &&
            focusedIndex < filteredEmails.length
          ) {
            const email = filteredEmails[focusedIndex];
            if (email) {
              archiveEmail(email.id);
            }
          }
          break;
        }
        case "#": {
          e.preventDefault();
          if (
            focusedIndex >= 0 &&
            focusedIndex < filteredEmails.length
          ) {
            const email = filteredEmails[focusedIndex];
            if (email) {
              trashEmail(email.id);
            }
          }
          break;
        }
        case "Escape": {
          e.preventDefault();
          clearSelections();
          setFocusedIndex(-1);
          break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    selectedEmailId,
    filteredEmails,
    focusedIndex,
    selectedKeys,
    onSelectionChange,
    clearSelections,
    archiveEmail,
    trashEmail,
  ]);

  // Reset focused index when emails change
  useEffect(() => {
    setFocusedIndex(-1);
  }, [activeTab, searchResults]);

  if (isLoading)
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Spinner />
      </div>
    );

  if (emailsError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-center">
        <div>
          <h3 className="text-lg font-medium text-white">
            Failed to load emails
          </h3>
          <p className="mt-1 text-sm text-gray-400">
            Check your internet connection and try again
          </p>
        </div>
        <Button
          color="primary"
          variant="flat"
          onPress={() => window.location.reload()}
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="relative flex h-full w-full flex-col">
      <EmailTabs activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Search bar (Task 30) */}
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-1.5">
        <Button
          size="sm"
          variant="light"
          isIconOnly
          aria-label={isSearchOpen ? "Close search" : "Search emails"}
          onPress={toggleSearch}
        >
          {isSearchOpen ? (
            <Cancel01Icon size={16} />
          ) : (
            <SearchIcon size={16} />
          )}
        </Button>
        {isSearchOpen && (
          <Input
            ref={searchInputRef}
            size="sm"
            variant="bordered"
            placeholder="Search emails..."
            value={searchQuery}
            onValueChange={handleSearchChange}
            startContent={
              <SearchIcon
                size={14}
                className="text-foreground-400"
              />
            }
            endContent={
              isSearching ? (
                <Spinner size="sm" />
              ) : searchQuery ? (
                <button
                  type="button"
                  onClick={clearSearch}
                  className="cursor-pointer"
                  aria-label="Clear search"
                >
                  <Cancel01Icon size={14} />
                </button>
              ) : null
            }
            classNames={{
              inputWrapper: "h-8 min-h-8 bg-zinc-900",
              input: "text-sm",
            }}
            className="max-w-xs"
            aria-label="Search emails"
          />
        )}
        {isSearchOpen && searchResults && (
          <span className="text-xs text-foreground-400">
            {filteredEmails.length} result
            {filteredEmails.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {selectedCount > 0 && (
        <SelectionToolbar
          selectedCount={selectedCount}
          onClear={clearSelections}
          onBulkMarkAsRead={bulkMarkAsRead}
          onBulkMarkAsUnread={bulkMarkAsUnread}
          onBulkStar={bulkStarEmails}
          onBulkArchive={bulkArchiveEmails}
          onBulkTrash={bulkTrashEmails}
        />
      )}

      <div className="flex-1 overflow-y-auto">
        {/* Mobile card layout (Task 33) */}
        <div className="block sm:hidden">
          {filteredEmails.length === 0 ? (
            <div className="p-4 text-center text-foreground-400">
              No emails found
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {filteredEmails.map((email, index) => (
                <div
                  key={email.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Email from ${email.from}: ${email.subject}`}
                  className={`flex cursor-pointer flex-col gap-1 px-3 py-3 transition-colors hover:bg-primary/20 ${
                    focusedIndex === index
                      ? "bg-primary/10"
                      : ""
                  } ${
                    email.labelIds?.includes("UNREAD")
                      ? "font-medium"
                      : "font-normal text-foreground-400"
                  }`}
                  onClick={() => openEmail(email)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openEmail(email);
                    }
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0 flex-1 truncate">
                      <EmailFrom from={email.from} />
                    </div>
                    <div className="flex items-center gap-1.5">
                      <AIAnalysisIndicator
                        hasAnalysis={emailAnalysisIndicators.hasAnalysis(
                          email.id,
                        )}
                      />
                      <span className="shrink-0 text-xs opacity-50">
                        {formatTime(email.time)}
                      </span>
                    </div>
                  </div>
                  <div className="truncate text-sm">
                    {email.subject}
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <div
                      role="button"
                      tabIndex={0}
                      aria-label="Star"
                      className="flex h-6 w-6 items-center justify-center text-zinc-300"
                      onClick={(e) =>
                        handleToggleStarStatus(e, email)
                      }
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" ||
                          e.key === " "
                        ) {
                          e.preventDefault();
                          e.stopPropagation();
                          toggleStarStatus(email);
                        }
                      }}
                    >
                      <StarIcon
                        size={15}
                        color="orange"
                        fill={
                          email?.labelIds?.includes(
                            "STARRED",
                          )
                            ? "orange"
                            : "transparent"
                        }
                      />
                    </div>
                    <div
                      role="button"
                      tabIndex={0}
                      aria-label="Archive"
                      className="flex h-6 w-6 items-center justify-center text-zinc-300"
                      onClick={(e) =>
                        handleArchiveEmail(e, email)
                      }
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" ||
                          e.key === " "
                        ) {
                          e.preventDefault();
                          e.stopPropagation();
                          archiveEmail(email.id);
                        }
                      }}
                    >
                      <Archive01Icon size={15} />
                    </div>
                    <div
                      role="button"
                      tabIndex={0}
                      aria-label="Move to Trash"
                      className="flex h-6 w-6 items-center justify-center text-zinc-300"
                      onClick={(e) =>
                        handleTrashEmail(e, email)
                      }
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" ||
                          e.key === " "
                        ) {
                          e.preventDefault();
                          e.stopPropagation();
                          trashEmail(email.id);
                        }
                      }}
                    >
                      <Delete02Icon size={15} color="red" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Desktop table layout (Task 33) */}
        <div className="hidden sm:block">
          <Table
            aria-label="Emails"
            selectionMode="multiple"
            selectedKeys={selectedKeys}
            onSelectionChange={(keys) =>
              onSelectionChange(keys as Set<string> | "all")
            }
            onRowAction={(key) => {
              const email = filteredEmails.find(
                (e) => e.id === String(key),
              );
              if (email) openEmail(email);
            }}
            classNames={{
              wrapper: "bg-transparent shadow-none",
              table: "min-w-full",
              tr: "cursor-pointer transition-colors hover:bg-primary/20",
              th: "bg-transparent text-foreground-500 text-xs",
            }}
            removeWrapper={false}
            isHeaderSticky
            hideHeader
          >
            <TableHeader>
              <TableColumn key="sender" width={200}>
                Sender
              </TableColumn>
              <TableColumn key="subject">Subject</TableColumn>
              <TableColumn key="analysis" width={40}>
                {" "}
              </TableColumn>
              <TableColumn key="time" width={120}>
                Time
              </TableColumn>
            </TableHeader>
            <TableBody
              items={filteredEmails}
              emptyContent="No emails found"
            >
              {(email) => {
                const emailIndex = filteredEmails.indexOf(email);
                return (
                  <TableRow
                    key={email.id}
                    className={`group relative ${
                      focusedIndex === emailIndex
                        ? "bg-primary/10"
                        : ""
                    } ${
                      email.labelIds?.includes("UNREAD")
                        ? "font-medium"
                        : "font-normal text-foreground-400"
                    }`}
                  >
                    <TableCell>
                      <EmailHoverSummary
                        emailId={email.id}
                        subject={email.subject}
                      >
                        <EmailFrom from={email.from} />
                      </EmailHoverSummary>
                    </TableCell>
                    <TableCell>
                      <span className="truncate">
                        {email.subject}
                      </span>
                    </TableCell>
                    <TableCell>
                      <AIAnalysisIndicator
                        hasAnalysis={emailAnalysisIndicators.hasAnalysis(
                          email.id,
                        )}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-sm opacity-50">
                          {formatTime(email.time)}
                        </span>
                        <div className="absolute right-2 flex items-center gap-1 rounded-lg bg-zinc-900 p-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                          {[
                            {
                              icon: StarIcon,
                              label: "Star",
                              iconProps: {
                                color: "orange",
                                fill: email?.labelIds?.includes(
                                  "STARRED",
                                )
                                  ? "orange"
                                  : "transparent",
                              },
                              onClick: (
                                e: React.MouseEvent,
                              ) =>
                                handleToggleStarStatus(
                                  e,
                                  email,
                                ),
                            },
                            {
                              icon: Archive01Icon,
                              label: "Archive",
                              iconProps: {},
                              onClick: (
                                e: React.MouseEvent,
                              ) =>
                                handleArchiveEmail(
                                  e,
                                  email,
                                ),
                            },
                            {
                              icon: Delete02Icon,
                              label: "Move to Trash",
                              iconProps: { color: "red" },
                              onClick: (
                                e: React.MouseEvent,
                              ) =>
                                handleTrashEmail(e, email),
                            },
                            {
                              icon: email?.labelIds?.includes(
                                "UNREAD",
                              )
                                ? CheckmarkSquare03Icon
                                : SquareIcon,
                              label:
                                email?.labelIds?.includes(
                                  "UNREAD",
                                )
                                  ? "Mark as Read"
                                  : "Mark as Unread",
                              iconProps: {},
                              onClick: (
                                e: React.MouseEvent,
                              ) =>
                                handleToggleReadStatus(
                                  e,
                                  email,
                                ),
                            },
                          ].map(
                            ({
                              icon: Icon,
                              label,
                              iconProps,
                              onClick,
                            }) => (
                              <Tooltip
                                key={label}
                                content={label}
                                placement="top"
                                className="z-50"
                                color="foreground"
                              >
                                <div
                                  role="button"
                                  aria-label={label}
                                  tabIndex={0}
                                  className="flex h-6 w-6 cursor-pointer items-center justify-center text-zinc-300"
                                  onClick={onClick}
                                  onKeyDown={(e) => {
                                    if (
                                      e.key === "Enter" ||
                                      e.key === " "
                                    ) {
                                      e.preventDefault();
                                      onClick(
                                        e as unknown as React.MouseEvent,
                                      );
                                    }
                                  }}
                                >
                                  <Icon
                                    size={17}
                                    {...iconProps}
                                  />
                                </div>
                              </Tooltip>
                            ),
                          )}
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              }}
            </TableBody>
          </Table>
        </div>

        {hasNextPage && (
          <div ref={bottomRef} className="flex justify-center p-4">
            <Spinner size="sm" />
          </div>
        )}
      </div>

      <ViewEmail
        mailId={selectedEmailId}
        threadMessages={threadMessages}
        isLoadingThread={isLoadingThread}
        onOpenChange={closeEmail}
      />
    </div>
  );
}
