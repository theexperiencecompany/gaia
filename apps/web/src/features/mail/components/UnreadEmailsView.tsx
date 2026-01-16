import type React from "react";

import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { Gmail, InboxUnreadIcon, Loading02Icon } from "@/icons";
import type { EmailData, EmailFetchData } from "@/types/features/mailTypes";

interface UnreadEmailsViewProps {
  emails?: EmailData[];
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
}

const UnreadEmailsView: React.FC<UnreadEmailsViewProps> = ({
  emails = [],
  isConnected = true,
  onConnect,
}) => {
  const isLoading = false; // Data is passed from parent, no loading state needed
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

  const isEmpty = !formattedEmails || formattedEmails.length === 0;

  return (
    <BaseCardView
      title="Unread emails"
      icon={<InboxUnreadIcon className="h-6 w-6 text-foreground-500" />}
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
      path="/mail"
    >
      {isLoading ? (
        <div className="flex h-full items-center justify-center">
          <Loading02Icon className="h-8 w-8 animate-spin text-foreground-500" />
        </div>
      ) : (
        <EmailListCard
          emails={formattedEmails}
          backgroundColor="bg-secondary-bg"
          maxHeight=""
          isCollapsible={false}
        />
      )}
    </BaseCardView>
  );
};

export default UnreadEmailsView;
