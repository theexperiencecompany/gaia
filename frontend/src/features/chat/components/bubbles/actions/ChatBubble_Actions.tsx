import { Button } from "@heroui/button";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { PinIcon, Task01Icon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";

interface ChatBubbleActionsProps {
  loading: boolean;
  text: string;
  pinned?: boolean;
  message_id: string;
}

export default function ChatBubble_Actions({
  message_id,
  loading,
  text,
  pinned = false,
}: ChatBubbleActionsProps) {
  const { id: convoIdParam } = useParams<{ id: string }>();
  const { updateConvoMessages } = useConversation();

  const copyToClipboard = () => {
    // Remove NEW_MESSAGE_BREAK tokens for cleaner copy
    const cleanText = text.replace(/<NEW_MESSAGE_BREAK>/g, "\n\n");
    navigator.clipboard.writeText(cleanText);
    toast.info("Copied to clipboard", {
      description: `${cleanText.slice(0, 30)}...`,
    });

    // toast.success("Copied to clipboard", {
    //   unstyled: true,
    //   classNames: {
    //     toast: "flex items-center p-3 rounded-xl gap-3 w-[350px] toast_custom",
    //     title: "text-black text-sm",
    //     description: "text-sm text-black",
    //   },
    //   duration: 3000,
    //   description: `${text.substring(0, 35)}...`,
    //   icon: <Task01Icon color="black" height="23" />,
    // });
  };

  const handlePinToggle = async () => {
    try {
      if (!convoIdParam) return;

      if (!message_id) return;

      // Pin/unpin the message
      await chatApi.togglePinMessage(convoIdParam, message_id, !pinned);

      toast.success(pinned ? "Message unpinned!" : "Message pinned!");

      // Fetch messages again to reflect the pin state
      const updatedMessages = await chatApi.fetchMessages(convoIdParam);

      updateConvoMessages(updatedMessages);
    } catch (error) {
      toast.error("Could not pin this message");
      console.error("Could not pin this message", error);
    }
  };

  return (
    <>
      {!loading && (
        <div className="flex w-fit items-center gap-2">
          <Button
            isIconOnly
            className="h-fit w-fit rounded-md p-0"
            style={{ minWidth: "22px" }}
            variant="light"
            onPress={copyToClipboard}
          >
            <Task01Icon className="cursor-pointer" height="20" width="20" />
          </Button>

          <Button
            isIconOnly
            className="h-fit w-fit rounded-md p-0"
            variant="light"
            onClick={handlePinToggle}
            color={pinned ? "primary" : "default"}
            // variant={pinned ? "solid" : "light"}
            style={{ minWidth: "22px" }}
          >
            <PinIcon
              className={`cursor-pointer`}
              color={pinned ? "#00bbff" : "#9b9b9b"}
              fill={pinned ? "#00bbff" : "transparent"}
              height="20"
              width="20"
            />
          </Button>
          {/*
          <TranslateDropdown
            text={text}
            index={index}
            trigger={
              <Button
                variant="light"
                className="w-fit p-0 h-fit rounded-md"
                isIconOnly
                style={{ minWidth: "22px" }}
              >
                <TranslateIcon height="22" className="cursor-pointer" />
              </Button>
            }
          /> */}

          {/* <TextToSpeech text={text} /> */}
        </div>
      )}
    </>
  );
}
