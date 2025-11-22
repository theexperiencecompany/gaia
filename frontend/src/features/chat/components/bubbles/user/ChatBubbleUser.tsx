import { Button } from "@heroui/button";
import Image from "next/image";
import { toast } from "sonner";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { useUser } from "@/features/auth/hooks/useUser";
import SelectedCalendarEventIndicator from "@/features/chat/components/composer/SelectedCalendarEventIndicator";
import SelectedToolIndicator from "@/features/chat/components/composer/SelectedToolIndicator";
import SelectedWorkflowIndicator from "@/features/chat/components/composer/SelectedWorkflowIndicator";
import { Task01Icon } from "@/icons";
import { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import ChatBubbleFilePreview from "./ChatBubbleFilePreview";
import ChatBubble_Actions from "../actions/ChatBubble_Actions";

export default function ChatBubbleUser({
  text,
  date,
  message_id,
  fileData = [],
  selectedTool,
  toolCategory,
  selectedWorkflow,
  selectedCalendarEvent,
  disableActions = false,
}: ChatBubbleUserProps & { disableActions?: boolean }) {
  const hasContent =
    !!text ||
    fileData.length > 0 ||
    !!selectedTool ||
    !!selectedWorkflow ||
    !!selectedCalendarEvent;

  const user = useUser();

  if (!hasContent) return null;

  return (
    <div className="flex w-full items-end justify-end gap-3">
      <div className="chat_bubble_container user group" id={message_id}>
        {fileData.length > 0 && <ChatBubbleFilePreview files={fileData} />}

        {selectedTool && (
          <div className="flex justify-end">
            <SelectedToolIndicator
              toolName={selectedTool}
              toolCategory={toolCategory}
            />
          </div>
        )}

        {selectedWorkflow && (
          <div className="flex justify-end">
            <SelectedWorkflowIndicator workflow={selectedWorkflow} />
          </div>
        )}

        {selectedCalendarEvent && (
          <div className="flex justify-end">
            <SelectedCalendarEventIndicator event={selectedCalendarEvent} />
          </div>
        )}

        {text?.trim() && (
          <div className="imessage-bubble imessage-from-me">
            {!!text && (
              <div className="flex max-w-[30vw] text-wrap whitespace-pre-wrap select-text">
                {text}
              </div>
            )}
          </div>
        )}

        <div
          className={`flex flex-col items-end justify-end gap-1 pb-3 transition-all ${disableActions ? "hidden" : "opacity-0 group-hover:opacity-100"}`}
        >
          {date && (
            <span className="flex flex-col text-xs text-zinc-400 select-text">
              {parseDate(date)}
            </span>
          )}

          {text && !disableActions && (
            <ChatBubble_Actions
              loading={false}
              text={text}
              message_id={message_id}
            />
          )}
        </div>
      </div>
      <div className="min-w-[40px]">
        <Avatar
          className={`relative rounded-full bg-black ${disableActions ? "bottom-0" : "bottom-11"}`}
        >
          <AvatarImage src={user?.profilePicture} alt="User Avatar" />
          <AvatarFallback>
            <Image
              src={"/images/avatars/default.webp"}
              width={35}
              height={35}
              alt="Default profile picture"
            />
          </AvatarFallback>
        </Avatar>
      </div>
    </div>
  );
}
