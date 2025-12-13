import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";

import { Gmail } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { useAppendToInput } from "@/stores/composerStore";
import type { EmailFetchData } from "@/types/features/mailTypes";

interface EmailListProps {
  emails?: EmailFetchData[] | null;
  backgroundColor?: string;
  maxHeight?: string;
  isCollapsible?: boolean;
}

function extractSenderName(from: string): string {
  // Extract name before email or use email if no name
  const match = from.match(/^"?([^"<]+)"?\s*</);
  if (match) {
    return match[1].trim();
  }

  // If no angle brackets, check for name before space
  const spaceMatch = from.match(/^([^<]+)\s+</);
  if (spaceMatch) {
    return spaceMatch[1].trim();
  }

  // Extract just the email part if no name
  const emailMatch = from.match(/<([^>]+)>/);
  if (emailMatch) {
    return emailMatch[1].split("@")[0];
  }

  return from.split("@")[0] || from;
}

function formatTime(time: string | null): string {
  if (!time) return "Yesterday";

  const date = new Date(time);
  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } else if (diffInHours < 48) {
    return "Yesterday";
  } else {
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  }
}

export default function EmailListCard({
  emails,
  backgroundColor = "bg-zinc-800",
  maxHeight = "max-h-[300px]",
  isCollapsible = true,
}: EmailListProps) {
  const appendToInput = useAppendToInput();

  const handleEmailClick = (email: EmailFetchData) => {
    if (email.thread_id) {
      const sender = extractSenderName(email.from);
      appendToInput(
        `Tell me about the mail with thread id: ${email.thread_id} from ${sender} with subject "${email.subject}"`,
      );
    }
  };

  if (emails) {
    const content = (
      <div
        className={`w-full max-w-2xl rounded-3xl ${backgroundColor} p-3 text-white`}
      >
        {/* Email List */}
        <ScrollShadow className={`${maxHeight} divide-y divide-zinc-800`}>
          {!!emails &&
            emails.length > 0 &&
            emails.map((email) => (
              <Tooltip
                key={email.id}
                content={`Ask about this email from ${extractSenderName(email.from || "Unknown Sender")}`}
                showArrow
                color="foreground"
                delay={0}
                closeDelay={0}
                disableAnimation
              >
                <div
                  className="group flex cursor-pointer items-center gap-4 p-3 transition-colors hover:bg-zinc-700"
                  onClick={() => handleEmailClick(email)}
                >
                  <div className="w-40 flex-shrink-0">
                    <span className="block truncate text-sm font-medium text-gray-300">
                      {extractSenderName(email.from || "Unknown Sender")}
                    </span>
                  </div>

                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-white group-hover:text-gray-100">
                      {email.subject || "Unknown Subject"}
                    </span>
                  </div>

                  {/* Time */}
                  <div className="w-20 flex-shrink-0 text-right">
                    <span className="text-xs text-gray-400">
                      {formatTime(email.time || null)}
                    </span>
                  </div>
                </div>
              </Tooltip>
            ))}
        </ScrollShadow>
      </div>
    );

    return (
      <CollapsibleListWrapper
        icon={<Gmail width={20} height={20} />}
        count={emails.length}
        label="Email"
        isCollapsible={isCollapsible}
      >
        {content}
      </CollapsibleListWrapper>
    );
  }
}
