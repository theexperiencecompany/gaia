"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  Archive01Icon,
  Cancel01Icon,
  CheckmarkSquare03Icon,
  Delete02Icon,
  SparklesIcon,
  SquareIcon,
  StarIcon,
  Timer02Icon,
} from "@icons";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  FixedSizeList as List,
  type ListChildComponentProps,
} from "react-window";
import InfiniteLoader from "react-window-infinite-loader";
import Spinner from "@/components/ui/spinner";
import { EmailFrom } from "@/features/mail/components/MailFrom";

// ssr:false — ViewMail pulls in @tiptap (~0.37 MB raw). Mail UI is fully
// interactive, no SEO need.
const ViewEmail = dynamic(() => import("@/features/mail/components/ViewMail"), {
  ssr: false,
});

import { useEmailActions } from "@/features/mail/hooks/useEmailActions";
import { useEmailAnalysisIndicators } from "@/features/mail/hooks/useEmailAnalysis";
import { useEmailGrouping } from "@/features/mail/hooks/useEmailGrouping";
import { useEmailReadStatus } from "@/features/mail/hooks/useEmailReadStatus";
import { useEmailSelection } from "@/features/mail/hooks/useEmailSelection";
import { useEmailViewer } from "@/features/mail/hooks/useEmailViewer";
import { useInfiniteEmails } from "@/features/mail/hooks/useInfiniteEmails";
import { formatTime } from "@/features/mail/utils/mailUtils";
import useMediaQuery from "@/hooks/ui/useMediaQuery";
import type { EmailData } from "@/types/features/mailTypes";

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

function MailsLoadingState() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <Spinner />
    </div>
  );
}

function MailsErrorState() {
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

function MailSelectionToolbar({
  selectedCount,
  onClear,
  onMarkRead,
  onMarkUnread,
  onStar,
  onArchive,
  onTrash,
}: {
  selectedCount: number;
  onClear: () => void;
  onMarkRead: () => void;
  onMarkUnread: () => void;
  onStar: () => void;
  onArchive: () => void;
  onTrash: () => void;
}) {
  if (selectedCount === 0) return null;
  return (
    <div className="absolute top-0 right-0 left-0 z-10 flex items-center justify-between rounded-md bg-zinc-900 px-1 py-1 text-white backdrop-blur-xl">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          color="default"
          variant="flat"
          onPress={onClear}
          startContent={<Cancel01Icon size={16} />}
        >
          Clear selection
        </Button>
        <span className="font-medium">{selectedCount} selected</span>
      </div>
      <div className="flex items-center gap-2">
        <Tooltip content="Mark as read">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onMarkRead}
            isIconOnly
            aria-label="Mark as read"
          >
            <CheckmarkSquare03Icon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Mark as unread">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onMarkUnread}
            isIconOnly
            aria-label="Mark as unread"
          >
            <SquareIcon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Star">
          <Button
            size="sm"
            color="warning"
            variant="light"
            onPress={onStar}
            isIconOnly
            aria-label="Star"
          >
            <StarIcon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Archive">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onArchive}
            isIconOnly
            aria-label="Archive"
          >
            <Archive01Icon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Move to trash">
          <Button
            size="sm"
            color="danger"
            variant="light"
            onPress={onTrash}
            isIconOnly
            aria-label="Move to trash"
          >
            <Delete02Icon size={16} />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

function MailHoverActions({
  email,
  onToggleStar,
  onArchive,
  onTrash,
  onToggleRead,
}: {
  email: EmailData;
  onToggleStar: (e: React.MouseEvent, email: EmailData) => void;
  onArchive: (e: React.MouseEvent, email: EmailData) => void;
  onTrash: (e: React.MouseEvent, email: EmailData) => void;
  onToggleRead: (e: React.MouseEvent, email: EmailData) => void;
}) {
  return (
    <div className="absolute right-0 flex h-fit w-fit items-center gap-1 rounded-lg bg-zinc-900 p-2 text-sm text-zinc-300 opacity-0 group-hover:opacity-100">
      {[
        {
          icon: StarIcon,
          label: "Star",
          iconProps: {
            color: "orange",
            fill: email?.labelIds?.includes("STARRED")
              ? "orange"
              : "transparent",
          },
          onClick: (e: React.MouseEvent) => onToggleStar(e, email),
        },
        {
          icon: Archive01Icon,
          label: "Archive",
          onClick: (e: React.MouseEvent) => onArchive(e, email),
        },
        {
          icon: Delete02Icon,
          label: "Move to Trash",
          iconProps: { color: "red" },
          onClick: (e: React.MouseEvent) => onTrash(e, email),
        },
        {
          icon: email?.labelIds?.includes("UNREAD")
            ? CheckmarkSquare03Icon
            : SquareIcon,
          label: email?.labelIds?.includes("UNREAD")
            ? "Mark as Read"
            : "Mark as Unread",
          onClick: (e: React.MouseEvent) => onToggleRead(e, email),
        },
        {
          icon: Timer02Icon,
          label: "Set Reminder",
          onClick: (e: React.MouseEvent) => e.stopPropagation(),
        },
      ].map(({ icon: Icon, label, iconProps, onClick }) => (
        <Tooltip
          key={label}
          content={label}
          placement="top"
          className="z-50"
          color="foreground"
        >
          <button
            type="button"
            aria-label={label}
            className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-none border-none bg-transparent p-0"
            onClick={onClick}
          >
            <Icon size={19} {...iconProps} />
          </button>
        </Tooltip>
      ))}
    </div>
  );
}

function MailMobileContent({
  email,
  hasAnalysis,
}: {
  email: EmailData;
  hasAnalysis: boolean;
}) {
  return (
    <>
      <div className="col-span-1 min-h-fit truncate text-lg sm:block">
        <EmailFrom from={email.from} />
      </div>

      <div className="col-span-1 mt-1 flex min-h-fit items-center gap-2 text-right text-sm opacity-50 sm:mt-0">
        <AIAnalysisIndicator hasAnalysis={hasAnalysis} />
        {formatTime(email.time)}
      </div>

      <div className="col-span-2 min-h-fit w-full truncate sm:col-span-1">
        {email.subject}
      </div>
    </>
  );
}

function MailDesktopContent({
  email,
  hasAnalysis,
  onToggleStar,
  onArchive,
  onTrash,
  onToggleRead,
}: {
  email: EmailData;
  hasAnalysis: boolean;
  onToggleStar: (e: React.MouseEvent, email: EmailData) => void;
  onArchive: (e: React.MouseEvent, email: EmailData) => void;
  onTrash: (e: React.MouseEvent, email: EmailData) => void;
  onToggleRead: (e: React.MouseEvent, email: EmailData) => void;
}) {
  return (
    <>
      <div className="col-span-1 min-h-fit truncate pl-2 sm:block">
        <EmailFrom from={email.from} />
      </div>

      <div className="col-span-2 min-h-fit w-full truncate sm:col-span-1">
        {email.subject}
      </div>

      <div className="col-span-1 mt-1 flex min-h-fit items-center gap-2 text-right text-sm opacity-50 sm:mt-0">
        <AIAnalysisIndicator hasAnalysis={hasAnalysis} />
        {formatTime(email.time)}
      </div>
      <MailHoverActions
        email={email}
        onToggleStar={onToggleStar}
        onArchive={onArchive}
        onTrash={onTrash}
        onToggleRead={onToggleRead}
      />
    </>
  );
}

function MailRow({
  index,
  style,
  groupedItems,
  isItemLoaded,
  selectedEmails,
  onToggleSelection,
  onOpenEmail,
  isMobileScreen,
  hasAnalysis,
  onToggleStar,
  onArchive,
  onTrash,
  onToggleRead,
}: ListChildComponentProps & {
  groupedItems: ReturnType<typeof useEmailGrouping>;
  isItemLoaded: (index: number) => boolean;
  selectedEmails: Set<string>;
  onToggleSelection: (e: React.MouseEvent, id: string) => void;
  onOpenEmail: (email: EmailData) => void;
  isMobileScreen: boolean;
  hasAnalysis: (id: string) => boolean;
  onToggleStar: (e: React.MouseEvent, email: EmailData) => void;
  onArchive: (e: React.MouseEvent, email: EmailData) => void;
  onTrash: (e: React.MouseEvent, email: EmailData) => void;
  onToggleRead: (e: React.MouseEvent, email: EmailData) => void;
}) {
  const [title, setTitle] = useState("");
  const subtitleRef = useRef("Lorem ipsum");

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
        className="relative flex h-full w-full items-center px-4 text-sm text-foreground/70 backdrop-blur-xs sm:px-1"
      >
        {item.data as string}
        <div className="absolute bottom-4 h-[1px] w-full border-none bg-white/20 outline-hidden sm:bottom-2"></div>
      </div>
    );

  const email = item.data as EmailData;

  const fetchSummary = (isOpen: boolean) => {
    if (isOpen && !title) {
      setTitle(email.subject);
    }
  };

  return (
    <Tooltip
      showArrow
      placement="top"
      delay={400}
      closeDelay={0}
      shouldCloseOnInteractOutside={() => true}
      onOpenChange={fetchSummary}
      content={
        <div className="flex w-[300px] flex-col p-1">
          <div className="text-lg leading-tight font-medium">{title}</div>
        </div>
      }
      onClose={() => {
        return !!title && !!subtitleRef.current;
      }}
      color="foreground"
      radius="sm"
    >
      <div
        className={`group relative grid w-full cursor-pointer gap-1 p-2 px-4 transition-all duration-200 hover:bg-primary/20 hover:text-primary sm:gap-2 sm:px-1 ${email?.labelIds?.includes("UNREAD") ? "font-medium" : "font-normal text-foreground-400"} sm:grid-cols-[auto_0.3fr_1fr_auto] sm:items-center`}
        style={style}
        onClick={() => onOpenEmail(email)}
      >
        <button
          type="button"
          aria-pressed={selectedEmails.has(email.id)}
          aria-label={
            selectedEmails.has(email.id) ? "Deselect email" : "Select email"
          }
          className="flex cursor-pointer items-center justify-center bg-transparent border-none p-0 px-2"
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelection(e, email.id);
          }}
        >
          {selectedEmails.has(email.id) ? (
            <CheckmarkSquare03Icon className="h-5 w-5 cursor-pointer text-primary" />
          ) : (
            <SquareIcon className="h-5 w-5 cursor-pointer opacity-60 hover:opacity-100" />
          )}
        </button>

        {isMobileScreen ? (
          <MailMobileContent
            email={email}
            hasAnalysis={hasAnalysis(email.id)}
          />
        ) : (
          <MailDesktopContent
            email={email}
            hasAnalysis={hasAnalysis(email.id)}
            onToggleStar={onToggleStar}
            onArchive={onArchive}
            onTrash={onTrash}
            onToggleRead={onToggleRead}
          />
        )}
      </div>
    </Tooltip>
  );
}

export default function MailsPage() {
  const isMobileScreen: boolean = useMediaQuery("(max-width: 600px)");
  const { toggleReadStatus: hookToggleReadStatus } = useEmailReadStatus();
  const { toggleStarStatus, archiveEmail, trashEmail } = useEmailActions();

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
  const handleToggleReadStatus = (e: React.MouseEvent, email: EmailData) => {
    e.stopPropagation();
    hookToggleReadStatus(email);
  };

  const handleToggleStarStatus = (e: React.MouseEvent, email: EmailData) => {
    e.stopPropagation();
    toggleStarStatus(email);
  };

  const handleArchiveEmail = (e: React.MouseEvent, email: EmailData) => {
    e.stopPropagation();
    archiveEmail(email.id);
  };

  const handleTrashEmail = (e: React.MouseEvent, email: EmailData) => {
    e.stopPropagation();
    trashEmail(email.id);
  };

  // Adapter for isItemLoaded to match the function signature expected by InfiniteLoader
  const isItemLoaded = useCallback(
    (index: number) => isItemLoadedBase(index, groupedItems.length),
    [isItemLoadedBase, groupedItems.length],
  );

  const hasAnalysis = useCallback(
    (id: string) => emailAnalysisIndicators.hasAnalysis(id),
    [emailAnalysisIndicators],
  );

  const itemCount = groupedItems.length + (emails.length > 0 ? 1 : 0);

  const Row = useCallback(
    (props: ListChildComponentProps) => (
      <MailRow
        {...props}
        groupedItems={groupedItems}
        isItemLoaded={isItemLoaded}
        selectedEmails={selectedEmails}
        onToggleSelection={toggleEmailSelection}
        onOpenEmail={openEmail}
        isMobileScreen={isMobileScreen}
        hasAnalysis={hasAnalysis}
        onToggleStar={handleToggleStarStatus}
        onArchive={handleArchiveEmail}
        onTrash={handleTrashEmail}
        onToggleRead={handleToggleReadStatus}
      />
    ),
    [
      groupedItems,
      isItemLoaded,
      selectedEmails,
      toggleEmailSelection,
      openEmail,
      isMobileScreen,
      hasAnalysis,
      handleToggleStarStatus,
      handleArchiveEmail,
      handleTrashEmail,
      handleToggleReadStatus,
    ],
  );

  if (isLoading) return <MailsLoadingState />;

  if (emailsError) return <MailsErrorState />;

  return (
    <div className="relative h-full w-full">
      <MailSelectionToolbar
        selectedCount={selectedEmails.size}
        onClear={clearSelections}
        onMarkRead={bulkMarkAsRead}
        onMarkUnread={bulkMarkAsUnread}
        onStar={bulkStarEmails}
        onArchive={bulkArchiveEmails}
        onTrash={bulkTrashEmails}
      />

      <InfiniteLoader
        isItemLoaded={isItemLoaded}
        itemCount={itemCount}
        loadMoreItems={loadMoreItems}
      >
        {({ onItemsRendered, ref }) => (
          <List
            height={window.innerHeight - 50}
            itemCount={itemCount}
            itemSize={isMobileScreen ? 70 : 55}
            onItemsRendered={onItemsRendered}
            ref={ref}
            width="100%"
            className="overflow-x-hidden! rounded-xl"
          >
            {Row}
          </List>
        )}
      </InfiniteLoader>

      <ViewEmail
        mailId={selectedEmailId}
        threadMessages={threadMessages}
        isLoadingThread={isLoadingThread}
        onOpenChange={closeEmail}
      />
    </div>
  );
}
