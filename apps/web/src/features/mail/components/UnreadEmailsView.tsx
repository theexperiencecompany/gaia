"use client";

import { Spinner } from "@heroui/spinner";
import {
  BookOpen01Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Edit02Icon,
  InboxUnreadIcon,
  Notification01Icon,
} from "@icons";
import type React from "react";
import { useMemo } from "react";
import { Gmail } from "@/components/shared/icons";
import type { CardAction } from "@/features/chat/components/interface/BaseCardView";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { useAppendToInput } from "@/stores/composerStore";
import type { EmailData, EmailFetchData } from "@/types/features/mailTypes";

interface UnreadEmailsViewProps {
  emails?: EmailData[];
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
  isFetching?: boolean;
  onLoadMore?: () => void;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
}

const UnreadEmailsView: React.FC<UnreadEmailsViewProps> = ({
  emails = [],
  isConnected = true,
  onConnect,
  isFetching = false,
  onLoadMore,
  hasNextPage,
  isFetchingNextPage,
}) => {
  const appendToInput = useAppendToInput();

  // Convert EmailData to EmailFetchData format expected by EmailListCard
  // and sort by time (most recent first)
  const formattedEmails: EmailFetchData[] =
    emails
      ?.map((email: EmailData) => ({
        from: email.from || "",
        subject: email.subject || "No Subject",
        time: email.time || "",
        thread_id: email.threadId,
        id: email.id,
      }))
      .sort((a, b) => {
        const timeA = new Date(a.time || 0).getTime();
        const timeB = new Date(b.time || 0).getTime();
        return timeB - timeA; // Most recent first
      }) || [];

  const isEmpty =
    !isFetching && (!formattedEmails || formattedEmails.length === 0);

  const actions: CardAction[] = useMemo(
    () => [
      {
        key: "triage",
        label: "Triage my inbox",
        description: "Rank emails by urgency and flag what needs a reply today",
        icon: <CheckListIcon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Please triage my unread emails. Rank them by urgency, identify which ones need a reply today, which can wait, and which I can ignore entirely.",
          ),
      },
      {
        key: "draft-replies",
        label: "Draft pending replies",
        description: "Generate draft replies for emails awaiting a response",
        icon: <Edit02Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Look through my unread emails and identify all the ones where someone is waiting for a reply from me. Then draft a reply for each one.",
          ),
      },
      {
        key: "action-items",
        label: "Extract action items",
        description: "Create todos from commitments buried in emails",
        icon: <CheckmarkCircle02Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Scan my unread emails and extract every action item, commitment, or task someone is waiting on me for. Create todos for each one.",
          ),
      },
      {
        key: "summarise-threads",
        label: "Summarise threads",
        description: "Collapse long email chains into 2-line catch-ups",
        icon: <BookOpen01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Summarise each of my unread email threads in 1–2 sentences so I can quickly understand what's going on without reading every message.",
          ),
      },
      {
        key: "follow-ups",
        label: "Chase no-replies",
        description: "Find sent emails with no response and draft follow-ups",
        icon: <Clock01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Find emails I sent more than 3 days ago that haven't received a reply yet, and draft a polite follow-up for each one.",
          ),
      },
      {
        key: "unsubscribe",
        label: "Unsubscribe audit",
        description:
          "List newsletters I haven't opened recently and offer to remove them",
        icon: <Notification01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Look through my inbox and identify newsletters or marketing emails I haven't opened in the past 30 days. List them and ask me which ones I'd like to unsubscribe from.",
          ),
      },
    ],
    [appendToInput],
  );

  return (
    <BaseCardView
      title="Unread emails"
      icon={<InboxUnreadIcon className="h-6 w-6 text-zinc-500" />}
      isFetching={isFetching}
      isEmpty={isEmpty}
      emptyMessage="No unread emails"
      errorMessage="Failed to load unread emails"
      isConnected={isConnected}
      connectIntegrationId="gmail"
      onConnect={onConnect}
      connectButtonText="Connect"
      connectTitle="Connect Your Gmail"
      connectDescription="Access and manage your emails"
      connectIcon={<Gmail width={32} height={32} />}
      actions={actions}
    >
      {isFetching ? (
        <div className="flex h-full items-center justify-center">
          <Spinner size="md" color="default" />
        </div>
      ) : (
        <EmailListCard
          emails={formattedEmails}
          backgroundColor="bg-secondary-bg"
          maxHeight=""
          isCollapsible={false}
          onLoadMore={onLoadMore}
          hasNextPage={hasNextPage}
          isFetchingNextPage={isFetchingNextPage}
        />
      )}
    </BaseCardView>
  );
};

export default UnreadEmailsView;
