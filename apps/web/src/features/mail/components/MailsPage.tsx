"use client";

import { Button } from "@heroui/button";
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
import { useMemo } from "react";

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
  CheckmarkSquare03Icon,
  Delete02Icon,
  SparklesIcon,
  SquareIcon,
  StarIcon,
  Timer02Icon,
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

  const handleToggleReadStatus = (e: React.MouseEvent, email: EmailData) => {
    e.stopPropagation();
    toggleReadStatus(email);
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
        <Table
          aria-label="Emails"
          selectionMode="multiple"
          selectedKeys={selectedKeys}
          onSelectionChange={(keys) =>
            onSelectionChange(keys as Set<string> | "all")
          }
          onRowAction={(key) => {
            const email = emails.find((e) => e.id === String(key));
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
          <TableBody items={emails} emptyContent="No emails found">
            {(email) => (
              <TableRow
                key={email.id}
                className={`group relative ${
                  email.labelIds?.includes("UNREAD")
                    ? "font-medium"
                    : "font-normal text-foreground-400"
                }`}
              >
                <TableCell>
                  <EmailHoverSummary emailId={email.id} subject={email.subject}>
                    <EmailFrom from={email.from} />
                  </EmailHoverSummary>
                </TableCell>
                <TableCell>
                  <span className="truncate">{email.subject}</span>
                </TableCell>
                <TableCell>
                  <AIAnalysisIndicator
                    hasAnalysis={emailAnalysisIndicators.hasAnalysis(email.id)}
                  />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-2">
                    <span className="text-sm opacity-50">
                      {formatTime(email.time)}
                    </span>
                    <div className="absolute right-2 flex items-center gap-1 rounded-lg bg-zinc-900 p-1 opacity-0 group-hover:opacity-100">
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
                          onClick: (e: React.MouseEvent) =>
                            handleToggleStarStatus(e, email),
                        },
                        {
                          icon: Archive01Icon,
                          label: "Archive",
                          iconProps: {},
                          onClick: (e: React.MouseEvent) =>
                            handleArchiveEmail(e, email),
                        },
                        {
                          icon: Delete02Icon,
                          label: "Move to Trash",
                          iconProps: { color: "red" },
                          onClick: (e: React.MouseEvent) =>
                            handleTrashEmail(e, email),
                        },
                        {
                          icon: email?.labelIds?.includes("UNREAD")
                            ? CheckmarkSquare03Icon
                            : SquareIcon,
                          label: email?.labelIds?.includes("UNREAD")
                            ? "Mark as Read"
                            : "Mark as Unread",
                          iconProps: {},
                          onClick: (e: React.MouseEvent) =>
                            handleToggleReadStatus(e, email),
                        },
                        {
                          icon: Timer02Icon,
                          label: "Set Reminder",
                          iconProps: {},
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
                          <div
                            className="flex h-6 w-6 cursor-pointer items-center justify-center text-zinc-300"
                            onClick={onClick}
                          >
                            <Icon size={17} {...iconProps} />
                          </div>
                        </Tooltip>
                      ))}
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

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
