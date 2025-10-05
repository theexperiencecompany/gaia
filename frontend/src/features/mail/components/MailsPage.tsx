"use client";

import { Button } from "@heroui/button";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Tooltip } from "@heroui/tooltip";
import type { LucideIcon } from "lucide-react";
import {
  ArchiveIcon,
  BellRing,
  CalendarClock,
  ClipboardList,
  Folder,
  Inbox,
  MoveRight,
  Reply,
  Scissors,
  Search,
  Sparkles,
  Square,
  SquareCheck,
  StarIcon,
  Timer,
  Trash,
  X,
} from "lucide-react";
import type { MouseEvent } from "react";
import { useCallback, useMemo, useState } from "react";
import { FixedSizeList as List, ListChildComponentProps } from "react-window";
import InfiniteLoader from "react-window-infinite-loader";

import { StarsIcon } from "@/components/shared/icons";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuTrigger,
} from "@/components/ui/shadcn/context-menu";
import Spinner from "@/components/ui/shadcn/spinner";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/shadcn/tabs";
import { EmailFrom } from "@/features/mail/components/MailFrom";
import ViewEmail from "@/features/mail/components/ViewMail";
import { useEmailActions } from "@/features/mail/hooks/useEmailActions";
import { useEmailAnalysisIndicators } from "@/features/mail/hooks/useEmailAnalysis";
import { useEmailGrouping } from "@/features/mail/hooks/useEmailGrouping";
import { useEmailReadStatus } from "@/features/mail/hooks/useEmailReadStatus";
import { useEmailSelection } from "@/features/mail/hooks/useEmailSelection";
import { useEmailViewer } from "@/features/mail/hooks/useEmailViewer";
import { useInfiniteEmails } from "@/features/mail/hooks/useInfiniteEmails";
import { formatTime } from "@/features/mail/utils/mailUtils";
import useMediaQuery from "@/hooks/ui/useMediaQuery";
import { EmailData } from "@/types/features/mailTypes";

function AIAnalysisIndicator({ hasAnalysis }: { hasAnalysis: boolean }) {
  if (!hasAnalysis) return null;

  return (
    <Tooltip content="AI Analysis Available" color="primary">
      <div className="flex items-center justify-center">
        <StarsIcon
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
  const isMobileScreen: boolean = useMediaQuery("(max-width: 600px)");
  const { toggleReadStatus: hookToggleReadStatus } = useEmailReadStatus();
  const { toggleStarStatus, archiveEmail, trashEmail } = useEmailActions();
  const [searchQuery, setSearchQuery] = useState("");

  // Get emails with infinite loading
  const {
    emails,
    isLoading,
    isItemLoaded: isItemLoadedBase,
    loadMoreItems,
    error: emailsError,
  } = useInfiniteEmails();

  const {
    selectedEmails,
    toggleEmailSelection,
    clearSelections,
    bulkMarkAsRead,
    bulkMarkAsUnread,
    bulkStarEmails,
    // bulkUnstarEmails,
    bulkArchiveEmails,
    bulkTrashEmails,
  } = useEmailSelection();

  const groupedItems = useEmailGrouping(emails);

  // Get all email IDs for bulk analysis check
  const emailIds = useMemo(() => emails.map((email) => email.id), [emails]);

  // Use bulk API to check which emails have analysis
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

  // Handlers for single email actions
  const handleToggleReadStatus = (e: MouseEvent, email: EmailData) => {
    e.stopPropagation(); // Prevent opening the email
    hookToggleReadStatus(email);
  };

  const handleToggleStarStatus = (e: MouseEvent, email: EmailData) => {
    e.stopPropagation(); // Prevent opening the email
    toggleStarStatus(email);
  };

  const handleArchiveEmail = (e: MouseEvent, email: EmailData) => {
    e.stopPropagation(); // Prevent opening the email
    archiveEmail(email.id);
  };

  const handleTrashEmail = (e: MouseEvent, email: EmailData) => {
    e.stopPropagation(); // Prevent opening the email
    trashEmail(email.id);
  };

  // Adapter for isItemLoaded to match the function signature expected by InfiniteLoader
  const isItemLoaded = useCallback(
    (index: number) => isItemLoadedBase(index, groupedItems.length),
    [isItemLoadedBase, groupedItems.length],
  );

  const viewportHeight =
    typeof window !== "undefined" ? window.innerHeight : 900;
  const listHeight = Math.max(viewportHeight - 360, 320);

  const focusGroups = useMemo<FocusZoneGroup[]>(() => {
    const actionable: EmailData[] = [];
    const informative: EmailData[] = [];
    const setAside: EmailData[] = [];
    const usedIds = new Set<string>();

    emails.forEach((email) => {
      if (
        actionable.length < 4 &&
        (email.labelIds?.includes("UNREAD") ||
          email.labelIds?.includes("STARRED"))
      ) {
        actionable.push(email);
        usedIds.add(email.id);
      }
    });

    emails.forEach((email) => {
      if (usedIds.has(email.id)) return;
      if (informative.length < 4 && email.labelIds?.includes("IMPORTANT")) {
        informative.push(email);
        usedIds.add(email.id);
      }
    });

    emails.forEach((email) => {
      if (usedIds.has(email.id)) return;
      if (setAside.length < 4) {
        setAside.push(email);
        usedIds.add(email.id);
      }
    });

    return [
      {
        id: "action",
        title: "Take action",
        accent: actionable.length
          ? `${actionable.length} prioritized`
          : "All clear",
        description:
          actionable.length > 0
            ? "Gaia flagged these threads that need your decision or response."
            : "Gaia will surface new priorities the moment they appear.",
        emails: actionable,
      },
      {
        id: "inform",
        title: "Important to know",
        accent: informative.length
          ? `${informative.length} highlighted`
          : "No alerts",
        description:
          "Context updates that matter but do not require immediate action.",
        emails: informative,
      },
      {
        id: "later",
        title: "Set aside",
        accent: setAside.length ? `${setAside.length} queued` : "Inbox calm",
        description:
          "Long reads and FYIs grouped for when you have breathing room.",
        emails: setAside,
      },
    ];
  }, [emails]);

  const smartStacks = useMemo<SmartStack[]>(() => {
    const [actionGroup, importantGroup, laterGroup] = focusGroups;
    const actionCount = actionGroup?.emails?.length ?? 0;
    const laterCount = laterGroup?.emails?.length ?? 0;
    const importantCount = importantGroup?.emails?.length ?? 0;
    return [
      {
        id: "reply-later",
        title: "Reply later",
        description: "Keep thoughtful responses a swipe away for later today.",
        accent: actionCount ? `${actionCount} queued` : "Empty",
        icon: Timer,
        items: actionGroup?.emails ?? [],
      },
      {
        id: "set-aside",
        title: "Set aside",
        description:
          "Archive distractions while knowing Gaia is watching them.",
        accent: laterCount ? `${laterCount} parked` : "Clean slate",
        icon: ArchiveIcon,
        items: laterGroup?.emails ?? [],
      },
      {
        id: "top-of-mind",
        title: "Top of mind",
        description:
          "Pin the narratives you want to keep in your working memory.",
        accent: importantCount
          ? `${importantCount} pinned`
          : "Awaiting signals",
        icon: StarIcon,
        items: importantGroup?.emails ?? [],
      },
    ];
  }, [focusGroups]);

  const reminderItems = useMemo(() => {
    const templates = [
      { label: "Later today", schedule: "Today • 4:00 PM" },
      { label: "Tomorrow morning", schedule: "Tomorrow • 9:00 AM" },
      { label: "Next week", schedule: "Mon • 8:30 AM" },
    ];

    return (
      focusGroups[0]?.emails?.slice(0, 3)?.map((email, index) => ({
        id: `${email.id}-reminder`,
        email,
        label: templates[index]?.label ?? "Someday soon",
        schedule: templates[index]?.schedule ?? "Queued",
      })) ?? []
    );
  }, [focusGroups]);

  const clipItems = useMemo(
    () =>
      emails.slice(0, 4).map((email, index) => ({
        id: `${email.id}-clip`,
        email,
        tag:
          index === 0
            ? "Action item"
            : index === 1
              ? "Decision"
              : index === 2
                ? "Reference"
                : "Idea",
        snippet:
          email.summary ??
          email.snippet ??
          "Select text in the preview to save it as a clip.",
      })),
    [emails],
  );

  const { unreadCount, starredCount, summaryCount } = useMemo(() => {
    let unread = 0;
    let starred = 0;
    let summary = 0;

    emails.forEach((email) => {
      if (email.labelIds?.includes("UNREAD")) unread += 1;
      if (email.labelIds?.includes("STARRED")) starred += 1;
      if (email.summary) summary += 1;
    });

    return {
      unreadCount: unread,
      starredCount: starred,
      summaryCount: summary,
    };
  }, [emails]);

  const autopilotSignals = useMemo(
    () => [
      summaryCount
        ? `${summaryCount} AI summaries ready`
        : "Gaia is preparing summaries",
      reminderItems.length
        ? `${reminderItems.length} reminders scheduled`
        : "No reminders queued",
      unreadCount
        ? `${unreadCount} unread prioritized`
        : "Inbox is clear right now",
    ],
    [summaryCount, reminderItems.length, unreadCount],
  );

  if (isLoading)
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Spinner />
      </div>
    );

  // Show error state when emails fail to load
  if (emailsError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-center">
        <div className="text-red-400">
          <svg
            className="h-12 w-12"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.464 0L4.35 16.5c-.77.833.192 2.5 1.732 2.5z"
            />
          </svg>
        </div>
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

  const Row = ({ index, style }: ListChildComponentProps) => {
    if (!isItemLoaded(index)) {
      return (
        <div style={style} className="flex items-center justify-center">
          <Spinner />
        </div>
      );
    }

    const item = groupedItems[index];
    if (!item) return null;

    if (item.type === "header")
      return (
        <div
          style={style}
          className="relative flex h-full w-full items-center px-6 text-xs font-semibold tracking-wide text-foreground/50 uppercase"
        >
          {item.data as string}
          <div className="absolute bottom-2 h-px w-full border-none bg-white/15 outline-hidden"></div>
        </div>
      );

    const email = item.data as EmailData;
    const summaryText =
      email.summary ??
      email.snippet ??
      "Gaia is drafting a summary for this thread.";
    const truncatedSummary =
      summaryText.length > 160 ? `${summaryText.slice(0, 157)}…` : summaryText;
    const isSelected = selectedEmails.has(email.id);

    return (
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <Tooltip
            showArrow
            placement="top"
            delay={400}
            closeDelay={0}
            shouldCloseOnInteractOutside={() => true}
            content={
              <div className="flex w-[320px] flex-col gap-1 p-1">
                <div className="text-sm font-semibold text-foreground">
                  {email.subject}
                </div>
                <p className="text-xs text-foreground/60">{summaryText}</p>
              </div>
            }
            color="foreground"
            radius="sm"
          >
            <div
              style={style}
              className={`group relative flex h-full w-full items-stretch gap-3 rounded-2xl border px-4 py-3 transition-colors duration-200 ${
                isSelected
                  ? "border-primary/40 bg-primary/10"
                  : "border-white/5 bg-black/10 hover:border-primary/40 hover:bg-primary/10"
              } ${
                email?.labelIds?.includes("UNREAD")
                  ? "text-foreground"
                  : "text-foreground/70"
              }`}
              onClick={() => openEmail(email)}
              onContextMenu={(event) => {
                if (!selectedEmails.has(email.id)) {
                  toggleEmailSelection(event, email.id);
                }
              }}
            >
              <div
                className="flex flex-shrink-0 items-start"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleEmailSelection(e, email.id);
                }}
              >
                {selectedEmails.has(email.id) ? (
                  <SquareCheck className="h-5 w-5 cursor-pointer text-primary" />
                ) : (
                  <Square className="h-5 w-5 cursor-pointer text-foreground/40 hover:text-foreground" />
                )}
              </div>

              <div className="flex flex-1 flex-col gap-2 overflow-hidden">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <EmailFrom from={email.from} />
                      {email.labelIds?.includes("STARRED") && (
                        <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs text-primary">
                          Pinned
                        </span>
                      )}
                    </div>
                    <div className="truncate text-base font-medium text-foreground">
                      {email.subject}
                    </div>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2 text-xs text-foreground/60">
                    <AIAnalysisIndicator
                      hasAnalysis={emailAnalysisIndicators.hasAnalysis(
                        email.id,
                      )}
                    />
                    {formatTime(email.time)}
                  </div>
                </div>
                <div
                  className={`flex flex-wrap items-center justify-between gap-3 ${
                    isMobileScreen ? "flex-col items-start" : ""
                  }`}
                >
                  <p className="min-w-0 flex-1 text-sm text-foreground/60">
                    {truncatedSummary}
                  </p>
                  <Button
                    size="sm"
                    variant="flat"
                    color="primary"
                    startContent={<Reply size={16} />}
                    onPress={(event) => {
                      openEmail(email);
                    }}
                  >
                    Reply
                  </Button>
                </div>
              </div>

              <div className="pointer-events-none absolute inset-y-3 right-4 hidden items-center gap-1 rounded-full border border-white/10 bg-black/70 px-2 py-1 text-xs text-foreground/60 shadow-sm backdrop-blur-sm transition group-hover:flex">
                {[
                  {
                    icon: StarIcon,
                    label: "Star",
                    action: (e: MouseEvent) => handleToggleStarStatus(e, email),
                    active: email?.labelIds?.includes("STARRED"),
                  },
                  {
                    icon: ArchiveIcon,
                    label: "Archive",
                    action: (e: MouseEvent) => handleArchiveEmail(e, email),
                  },
                  {
                    icon: Trash,
                    label: "Delete",
                    action: (e: MouseEvent) => handleTrashEmail(e, email),
                  },
                  {
                    icon: email?.labelIds?.includes("UNREAD")
                      ? SquareCheck
                      : Square,
                    label: email?.labelIds?.includes("UNREAD")
                      ? "Mark as read"
                      : "Mark as unread",
                    action: (e: MouseEvent) => handleToggleReadStatus(e, email),
                    active: email?.labelIds?.includes("UNREAD"),
                  },
                  {
                    icon: Timer,
                    label: "Reminder",
                    action: (e: MouseEvent) => e.stopPropagation(),
                  },
                  {
                    icon: Folder,
                    label: "Move",
                    action: (e: MouseEvent) => e.stopPropagation(),
                  },
                ].map(({ icon: Icon, label, action, active }, idx) => (
                  <Tooltip key={idx} content={label} color="foreground">
                    <div
                      className="pointer-events-auto flex h-6 w-6 cursor-pointer items-center justify-center rounded-full hover:bg-white/10"
                      onClick={action}
                    >
                      <Icon
                        size={16}
                        className={
                          active ? "text-primary" : "text-foreground/70"
                        }
                      />
                    </div>
                  </Tooltip>
                ))}
              </div>
            </div>
          </Tooltip>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-56 border-white/10 bg-black/90 text-foreground">
          <ContextMenuLabel>Focus controls</ContextMenuLabel>
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <Reply size={16} /> Reply now
            <ContextMenuShortcut>R</ContextMenuShortcut>
          </ContextMenuItem>
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <Sparkles size={16} /> Summarize with Gaia
          </ContextMenuItem>
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <ClipboardList size={16} /> Add to Reply later
          </ContextMenuItem>
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <BellRing size={16} /> Remind me later
          </ContextMenuItem>
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <Folder size={16} /> Move to workspace
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem onSelect={(event) => event.preventDefault()}>
            <Trash size={16} /> Delete thread
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    );
  };

  const itemCount = groupedItems.length + (emails.length > 0 ? 1 : 0);

  return (
    <div className="flex h-full w-full flex-col gap-6 pb-10">
      <header className="rounded-3xl border border-white/5 bg-black/30 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-primary uppercase">
              <Sparkles size={16} />
              Gaia mailroom
            </div>
            <h1 className="text-2xl font-semibold text-foreground">
              Focused inbox, powered by Gaia
            </h1>
            <p className="max-w-2xl text-sm text-foreground/60">
              Gaia triages every thread, summarises intent, and keeps decisive
              actions one click away.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="flat"
              color="default"
              startContent={<Scissors size={16} />}
              onPress={() => undefined}
            >
              New clip
            </Button>
            <Button color="primary" onPress={() => undefined}>
              Compose
            </Button>
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3">
          <div className="flex flex-col gap-3 sm:flex-row">
            <Input
              value={searchQuery}
              onValueChange={setSearchQuery}
              variant="faded"
              placeholder="Ask Gaia to find a plan, promise, or person"
              className="sm:flex-1"
              startContent={<Search size={16} className="text-foreground/50" />}
              endContent={
                <div className="flex items-center gap-2 text-xs text-foreground/50">
                  <Sparkles size={14} />
                  Semantic
                </div>
              }
            />
            <Button
              variant="flat"
              color="default"
              className="sm:w-auto"
              startContent={<MoveRight size={16} />}
              onPress={() => undefined}
            >
              Ask Gaia
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {autopilotSignals.map((signal) => (
              <Chip
                key={signal}
                variant="flat"
                color="default"
                className="border border-white/10 bg-white/5 text-xs text-foreground/70"
              >
                {signal}
              </Chip>
            ))}
          </div>
        </div>
      </header>

      <Tabs defaultValue="inbox" className="flex flex-1 flex-col gap-4">
        <TabsList className="w-fit rounded-full border border-white/10 bg-black/40 p-1">
          <TabsTrigger value="inbox" className="rounded-full px-4 py-2 text-sm">
            Inbox
          </TabsTrigger>
          <TabsTrigger value="focus" className="rounded-full px-4 py-2 text-sm">
            Focus zone
          </TabsTrigger>
        </TabsList>

        <TabsContent value="inbox" className="flex flex-1 flex-col gap-4">
          <div className="grid flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <section className="relative flex flex-col overflow-hidden rounded-2xl border border-white/5 bg-black/30">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 px-6 py-4">
                <div className="flex flex-wrap items-center gap-2 text-xs text-foreground/60">
                  <span className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 font-medium tracking-wider text-foreground/70 uppercase">
                    <Inbox size={14} />
                    Normal view
                  </span>
                  <span>{unreadCount} unread curated</span>
                  <span>•</span>
                  <span>{starredCount} pinned for follow-up</span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="light"
                    color="default"
                    startContent={<Sparkles size={16} />}
                    onPress={() => undefined}
                  >
                    Auto summarize
                  </Button>
                  <Button
                    size="sm"
                    variant="light"
                    color="default"
                    startContent={<ClipboardList size={16} />}
                    onPress={() => undefined}
                  >
                    Bulk triage
                  </Button>
                </div>
              </div>

              <div className="relative flex-1">
                {selectedEmails.size > 0 && (
                  <div className="pointer-events-auto absolute top-4 right-4 left-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/80 px-4 py-3 text-sm text-foreground shadow-lg backdrop-blur">
                    <div className="flex items-center gap-3">
                      <Button
                        size="sm"
                        color="default"
                        variant="flat"
                        onPress={clearSelections}
                        startContent={<X size={16} />}
                      >
                        Clear selection
                      </Button>
                      <span className="text-xs tracking-wide text-foreground/60 uppercase">
                        {selectedEmails.size} selected
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Tooltip content="Mark as read">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={bulkMarkAsRead}
                          isIconOnly
                        >
                          <SquareCheck size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Mark as unread">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={bulkMarkAsUnread}
                          isIconOnly
                        >
                          <Square size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Star">
                        <Button
                          size="sm"
                          color="warning"
                          variant="light"
                          onPress={bulkStarEmails}
                          isIconOnly
                        >
                          <StarIcon size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Archive">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={bulkArchiveEmails}
                          isIconOnly
                        >
                          <ArchiveIcon size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Delete">
                        <Button
                          size="sm"
                          color="danger"
                          variant="light"
                          onPress={bulkTrashEmails}
                          isIconOnly
                        >
                          <Trash size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Summarize">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={() => undefined}
                          isIconOnly
                        >
                          <Sparkles size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Remind later">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={() => undefined}
                          isIconOnly
                        >
                          <BellRing size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Move to">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={() => undefined}
                          isIconOnly
                        >
                          <Folder size={16} />
                        </Button>
                      </Tooltip>
                      <Tooltip content="Clip">
                        <Button
                          size="sm"
                          color="default"
                          variant="light"
                          onPress={() => undefined}
                          isIconOnly
                        >
                          <Scissors size={16} />
                        </Button>
                      </Tooltip>
                    </div>
                  </div>
                )}

                <div
                  className={
                    selectedEmails.size > 0 ? "h-full pt-16" : "h-full"
                  }
                >
                  <InfiniteLoader
                    isItemLoaded={isItemLoaded}
                    itemCount={itemCount}
                    loadMoreItems={loadMoreItems}
                  >
                    {({ onItemsRendered, ref }) => (
                      <List
                        height={listHeight}
                        itemCount={itemCount}
                        itemSize={isMobileScreen ? 130 : 120}
                        onItemsRendered={onItemsRendered}
                        ref={ref}
                        width="100%"
                        className="overflow-x-hidden"
                      >
                        {Row}
                      </List>
                    )}
                  </InfiniteLoader>
                </div>
              </div>
            </section>

            <aside className="flex flex-col gap-4">
              {smartStacks.map((stack) => (
                <Card
                  key={stack.id}
                  className="border-white/10 bg-black/30 text-foreground"
                >
                  <CardHeader className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-sm font-semibold tracking-wider text-foreground/70 uppercase">
                        <stack.icon size={16} className="text-primary" />
                        {stack.title}
                      </span>
                      <Chip size="sm" variant="flat" color="primary">
                        {stack.accent}
                      </Chip>
                    </div>
                    <p className="text-xs text-foreground/60">
                      {stack.description}
                    </p>
                  </CardHeader>
                  <CardBody className="flex flex-col gap-3">
                    {stack.items.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-white/10 p-3 text-xs text-foreground/50">
                        Gaia will drop threads here as soon as it spots the
                        right intent.
                      </div>
                    ) : (
                      stack.items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => openEmail(item)}
                          className="flex flex-col gap-1 rounded-lg border border-white/5 bg-zinc-900/40 p-3 text-left transition hover:border-primary/40 hover:bg-primary/10"
                        >
                          <div className="flex items-center justify-between text-xs text-foreground/60">
                            <EmailFrom from={item.from} />
                            <span>{formatTime(item.time)}</span>
                          </div>
                          <div className="text-sm font-medium text-foreground">
                            {item.subject}
                          </div>
                          <p className="line-clamp-2 text-xs text-foreground/60">
                            {item.summary ??
                              item.snippet ??
                              "Gaia suggests revisiting this when you have headspace."}
                          </p>
                        </button>
                      ))
                    )}
                  </CardBody>
                </Card>
              ))}

              <Card className="border-white/10 bg-black/30 text-foreground">
                <CardHeader className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-sm font-semibold tracking-wider text-foreground/70 uppercase">
                      <CalendarClock size={16} className="text-primary" />
                      Remind me later
                    </div>
                    <p className="text-xs text-foreground/60">
                      Snoozed mails resurface exactly when you need them.
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="light"
                    color="default"
                    onPress={() => undefined}
                  >
                    Schedule
                  </Button>
                </CardHeader>
                <CardBody className="flex flex-col gap-3">
                  {reminderItems.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-white/10 p-3 text-xs text-foreground/50">
                      Nothing queued yet. Right-click any mail to set a
                      reminder.
                    </div>
                  ) : (
                    reminderItems.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-start justify-between gap-3 rounded-lg border border-white/5 bg-zinc-900/40 p-3"
                      >
                        <div className="space-y-1">
                          <div className="text-sm font-medium text-foreground">
                            {item.email.subject}
                          </div>
                          <p className="text-xs text-foreground/60">
                            {item.schedule}
                          </p>
                        </div>
                        <Chip size="sm" variant="flat" color="default">
                          {item.label}
                        </Chip>
                      </div>
                    ))
                  )}
                </CardBody>
              </Card>

              <Card className="border-white/10 bg-black/30 text-foreground">
                <CardHeader className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-sm font-semibold tracking-wider text-foreground/70 uppercase">
                      <Scissors size={16} className="text-primary" />
                      Clips
                    </div>
                    <p className="text-xs text-foreground/60">
                      Keep the exact sentences and stats you want at a glance.
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="light"
                    color="default"
                    onPress={() => undefined}
                  >
                    Add clip
                  </Button>
                </CardHeader>
                <CardBody className="flex flex-col gap-3">
                  {clipItems.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-white/10 p-3 text-xs text-foreground/50">
                      Select any text in an email preview to pin it here.
                    </div>
                  ) : (
                    clipItems.map((clip) => (
                      <div
                        key={clip.id}
                        className="flex flex-col gap-2 rounded-lg border border-white/5 bg-zinc-900/40 p-3"
                      >
                        <div className="flex items-center justify-between text-xs text-foreground/60">
                          <span>{clip.tag}</span>
                          <span>{formatTime(clip.email.time)}</span>
                        </div>
                        <div className="text-sm text-foreground">
                          {clip.snippet}
                        </div>
                        <button
                          type="button"
                          className="w-fit text-xs text-primary underline-offset-2 hover:underline"
                          onClick={() => openEmail(clip.email)}
                        >
                          Jump to email
                        </button>
                      </div>
                    ))
                  )}
                </CardBody>
              </Card>
            </aside>
          </div>
        </TabsContent>

        <TabsContent value="focus" className="flex flex-1 flex-col">
          <FocusZoneView
            groups={focusGroups}
            onOpenEmail={openEmail}
            hasSummary={emailAnalysisIndicators.hasAnalysis}
          />
        </TabsContent>
      </Tabs>

      <ViewEmail
        mailId={selectedEmailId}
        threadMessages={threadMessages}
        isLoadingThread={isLoadingThread}
        onOpenChange={closeEmail}
      />
    </div>
  );
}

type SmartStack = {
  id: string;
  title: string;
  description: string;
  accent: string;
  icon: LucideIcon;
  items: EmailData[];
};

type FocusZoneGroup = {
  id: string;
  title: string;
  accent: string;
  description: string;
  emails: EmailData[];
};

function FocusZoneView({
  groups,
  onOpenEmail,
  hasSummary,
}: {
  groups: FocusZoneGroup[];
  onOpenEmail: (email: EmailData) => void;
  hasSummary: (id: string) => boolean;
}) {
  const totalItems = groups.reduce(
    (total, group) => total + group.emails.length,
    0,
  );

  return (
    <div className="flex flex-col gap-6 pb-8">
      <Card className="border-white/10 bg-black/30 text-foreground">
        <CardHeader className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-primary/10 p-2 text-primary">
              <Sparkles size={18} />
            </div>
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-foreground">
                Your focus brief
              </h2>
              <p className="text-sm text-foreground/60">
                {totalItems
                  ? `Gaia condensed ${totalItems} threads into distraction-free lanes.`
                  : "Gaia will assemble a brief the moment new intent arrives."}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Chip size="sm" variant="flat" color="default">
              Distraction free
            </Chip>
            <Chip size="sm" variant="flat" color="primary">
              Summaries on
            </Chip>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        {groups.map((group) => (
          <Card
            key={group.id}
            className="border-white/10 bg-black/30 text-foreground"
          >
            <CardHeader className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold tracking-wider text-foreground/70 uppercase">
                  {group.title}
                </span>
                <span className="text-xs text-primary">{group.accent}</span>
              </div>
              <p className="text-xs text-foreground/60">{group.description}</p>
            </CardHeader>
            <CardBody className="flex flex-col gap-3">
              {group.emails.length === 0 ? (
                <div className="rounded-lg border border-dashed border-white/10 p-4 text-xs text-foreground/50">
                  Gaia will surface threads here once it understands the intent.
                </div>
              ) : (
                group.emails.map((email) => {
                  const summary =
                    email.summary ??
                    email.snippet ??
                    "Gaia is generating a summary for this conversation.";

                  return (
                    <button
                      key={email.id}
                      type="button"
                      onClick={() => onOpenEmail(email)}
                      className="group flex flex-col gap-2 rounded-xl border border-white/5 bg-zinc-900/40 p-3 text-left transition hover:border-primary/40 hover:bg-primary/10"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <EmailFrom from={email.from} />
                        <div className="flex items-center gap-1 text-xs text-foreground/60">
                          <AIAnalysisIndicator
                            hasAnalysis={hasSummary(email.id)}
                          />
                          {formatTime(email.time)}
                        </div>
                      </div>
                      <div className="text-sm font-medium text-foreground">
                        {email.subject}
                      </div>
                      <p className="line-clamp-2 text-xs text-foreground/60">
                        {summary}
                      </p>
                      <div className="flex items-center justify-between text-xs text-primary">
                        <span className="flex items-center gap-1">
                          <Sparkles size={14} /> Guided by Gaia
                        </span>
                        <span className="flex items-center gap-1 text-foreground/60 group-hover:text-primary">
                          <Reply size={14} /> Reply
                        </span>
                      </div>
                    </button>
                  );
                })
              )}
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}
