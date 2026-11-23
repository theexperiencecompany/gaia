import { Chip } from "@heroui/react";
import { CheckmarkCircle02Icon } from "@icons";
import {
  FIXED_LOCALE,
  formatRelativeDate,
  formatTime as formatTimeOfDay,
} from "@shared/utils";
import { Gmail } from "@/components/shared/icons";
import type { EmailSentData } from "@/types/features/mailTypes";

interface EmailSentCardProps {
  emailSentData: EmailSentData;
}

const SECONDS_PER_HOUR = 3600;

const formatClockOf = (timestamp: string) =>
  formatTimeOfDay(timestamp, { locale: FIXED_LOCALE });

const formatTime = (timestamp?: string) => {
  if (!timestamp) return "Just now";
  const secondsAgo = (Date.now() - new Date(timestamp).getTime()) / 1000;
  return secondsAgo < SECONDS_PER_HOUR
    ? formatRelativeDate(timestamp, { locale: FIXED_LOCALE })
    : formatClockOf(timestamp);
};

export default function EmailSentCard({ emailSentData }: EmailSentCardProps) {
  return (
    <div className="w-full min-w-fit max-w-xs rounded-2xl bg-green-900/20 p-4 text-white">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Gmail width={20} height={20} />
          <CheckmarkCircle02Icon className="h-5 w-5 text-green-400" />
          <span className="text-sm font-medium text-green-400">Email Sent</span>
        </div>
        <Chip size="sm" variant="soft" color="success" className="text-xs">
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
