import { Loader2 } from "lucide-react";
import React from "react";

import { Gmail } from "@/components";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { EmailData, EmailFetchData } from "@/types/features/mailTypes";

interface UnreadEmailsViewProps {
  emails?: EmailData[];
  isLoading: boolean;
  error?: Error | null;
  // Connection state props
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
  onRefresh?: () => void;
}

const UnreadEmailsView: React.FC<UnreadEmailsViewProps> = ({
  emails,
  isLoading,
  error,
  isConnected = true,
  onConnect,
  onRefresh,
}) => {
  // Convert EmailData to EmailFetchData format expected by EmailListCard
  const formattedEmails: EmailFetchData[] =
    emails?.map((email: EmailData) => ({
      from: email.from || "",
      subject: email.subject || "No Subject",
      time: email.time || "",
      thread_id: email.threadId || email.id,
    })) || [];

  const isEmpty = !formattedEmails || formattedEmails.length === 0;

  return (
    <BaseCardView
      title="Unread emails"
      icon={<Gmail className="h-5 w-5 text-zinc-500" />}
      isLoading={isLoading}
      error={error?.message}
      isEmpty={isEmpty}
      emptyMessage="No unread emails"
      errorMessage="Failed to load unread emails"
      isConnected={isConnected}
      connectIntegrationId="gmail"
      onConnect={onConnect}
      connectButtonText="Connect Gmail"
      onRefresh={onRefresh}
    >
      {isLoading ? (
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-zinc-500" />
        </div>
      ) : (
        <EmailListCard
          emails={formattedEmails}
          backgroundColor="bg-[#141414]"
          showTitle={false}
          maxHeight=""
          isCollapsible={false}
        />
      )}
    </BaseCardView>
  );
};

export default UnreadEmailsView;
