import React from "react";

import { Gmail } from "@/components";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { Loading02Icon } from '@/icons';
import { EmailData, EmailFetchData } from "@/types/features/mailTypes";

interface UnreadEmailsViewProps {
  emails?: EmailData[];
  isLoading: boolean;
  isFetching?: boolean;
  error?: Error | null;
  // Connection state props
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
  onRefresh?: () => void;
}

const UnreadEmailsView: React.FC<UnreadEmailsViewProps> = ({
  emails,
  isLoading,
  isFetching = false,
  error,
  isConnected = true,
  onConnect,
  onRefresh,
}) => {
  // Convert EmailData to EmailFetchData format expected by EmailListCard
  // and sort by time (most recent first)
  const formattedEmails: EmailFetchData[] =
    emails
      ?.map((email: EmailData) => ({
        from: email.from || "",
        subject: email.subject || "No Subject",
        time: email.time || "",
        thread_id: email.threadId || email.id,
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
      icon={<Gmail className="h-5 w-5 text-zinc-500" />}
      isFetching={isFetching}
      error={error?.message}
      isEmpty={isEmpty}
      emptyMessage="No unread emails"
      errorMessage="Failed to load unread emails"
      isConnected={isConnected}
      connectIntegrationId="gmail"
      onConnect={onConnect}
      connectButtonText="Connect Gmail"
      connectTitle="Connect Your Gmail"
      connectDescription="Access and manage your emails"
      connectIcon={<Gmail width={32} height={32} />}
      onRefresh={onRefresh}
    >
      {isLoading ? (
        <div className="flex h-full items-center justify-center">
          <Loading02Icon className="h-8 w-8 animate-spin text-zinc-500" />
        </div>
      ) : (
        <EmailListCard
          emails={formattedEmails}
          backgroundColor="bg-[#141414]"
          maxHeight=""
          isCollapsible={false}
        />
      )}
    </BaseCardView>
  );
};

export default UnreadEmailsView;
