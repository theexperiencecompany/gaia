import { Chip } from "@heroui/chip";

import { Gmail } from "@/components";
import { CheckmarkCircle02Icon } from '@/icons';
import { EmailSentData } from "@/types/features/mailTypes";

interface EmailSentCardProps {
  emailSentData: EmailSentData;
}

export default function EmailSentCard({ emailSentData }: EmailSentCardProps) {
  const formatTime = (timestamp?: string) => {
    if (!timestamp) return "Just now";

    const date = new Date(timestamp);
    const now = new Date();
    const diffInSeconds = (now.getTime() - date.getTime()) / 1000;

    if (diffInSeconds < 60) return "Just now";
    if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  };

  return (
    <div className="w-full max-w-2xl rounded-2xl border border-green-700/30 bg-green-900/20 p-4 text-white">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Gmail width={20} height={20} />
          <CheckmarkCircle02Icon className="h-5 w-5 text-green-400" />
          <span className="text-sm font-medium text-green-400">Email Sent</span>
        </div>
        <Chip size="sm" variant="flat" color="success" className="text-xs">
          {formatTime(emailSentData.timestamp)}
        </Chip>
      </div>

      {/* Email Details */}
      <div className="space-y-2">
        {emailSentData.subject && (
          <div className="text-sm">
            <span className="text-gray-400">Subject: </span>
            <span className="text-gray-200">{emailSentData.subject}</span>
          </div>
        )}

        {emailSentData.recipients && emailSentData.recipients.length > 0 && (
          <div className="text-sm">
            <span className="text-gray-400">To: </span>
            <span className="text-gray-200">
              {emailSentData.recipients.join(", ")}
            </span>
          </div>
        )}

        <div className="text-sm font-medium text-green-400">
          {emailSentData.message}
        </div>
      </div>
    </div>
  );
}
