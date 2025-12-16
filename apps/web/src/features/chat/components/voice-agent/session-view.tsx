import {
  type AgentState,
  useRoomContext,
  useVoiceAssistant,
} from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import { toast } from "sonner";

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { AgentControlBar } from "@/features/chat/components/voice-agent/agent-control-bar";
import useChatAndTranscription from "@/features/chat/components/voice-agent/hooks/useChatAndTranscription";
import { MediaTiles } from "@/features/chat/components/voice-agent/media-tiles";
import { db, type IMessage } from "@/lib/db/chatDb";
import { cn } from "@/lib/utils";
import type { MessageType } from "@/types/features/convoTypes";

function isAgentAvailable(agentState: AgentState) {
  return (
    agentState === "listening" ||
    agentState === "thinking" ||
    agentState === "speaking"
  );
}

interface SessionViewProps {
  disabled: boolean;
  sessionStarted: boolean;
  onEndCall: () => void;
}

export const SessionView = ({
  disabled,
  sessionStarted,
  onEndCall,
  ref,
}: React.ComponentProps<"div"> & SessionViewProps) => {
  const { state: agentState } = useVoiceAssistant();
  const [chatOpen, setChatOpen] = useState(false);
  const { messages } = useChatAndTranscription();
  const room = useRoomContext();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (!room) {
      return;
    }

    const conversationIdHandler = (reader: TextStreamReader) => {
      if (reader.info.topic === "conversation-id") {
        const handleStream = async () => {
          try {
            const text = await reader.readAll();
            setConversationId(text);
            console.log(`Received conversation ID via text stream: ${text}`);
          } catch (err) {
            console.error("Failed to read text stream:", err);
          }
        };
        handleStream();
      }
    };

    const registerHandler = () => {
      try {
        room.unregisterTextStreamHandler("conversation-id");
      } catch {
        // Ignore error if no handler was registered
      }

      room.registerTextStreamHandler("conversation-id", conversationIdHandler);
      console.log("Registered conversation-id text stream handler.");
    };

    room.on("connected", registerHandler);

    if (room.state === "connected") {
      registerHandler();
    }

    return () => {
      room.off("connected", registerHandler);
      try {
        room.unregisterTextStreamHandler("conversation-id");
      } catch {
        // Ignore error if no handler was registered
      }
    };
  }, [room]);

  const handleEndCall = React.useCallback(async () => {
    // Persist voice mode messages to IndexedDB
    if (conversationId && messages.length > 0) {
      const messagesToPersist: IMessage[] = messages
        .filter((msg: MessageType) => msg.message_id) // Only persist messages with valid IDs
        .map((msg: MessageType) => ({
          id: msg.message_id!,
          conversationId: conversationId,
          content: msg.response ?? "",
          role:
            msg.type === "user" ? ("user" as const) : ("assistant" as const),
          status: "sent" as const,
          createdAt: msg.date ? new Date(msg.date) : new Date(),
          updatedAt: new Date(),
          messageId: msg.message_id!,
        }));

      try {
        await db.putMessagesBulk(messagesToPersist);
      } catch (error) {
        console.error("Failed to persist voice messages to IndexedDB:", error);
      }
    }

    if (conversationId) {
      router.push(`/c/${conversationId}`);
    } else {
      console.log("No conversationId found, staying on current page.");
    }
    onEndCall();
  }, [onEndCall, conversationId, router, messages]);

  useEffect(() => {
    if (sessionStarted) {
      const timeout = setTimeout(() => {
        if (!isAgentAvailable(agentState)) {
          const reason =
            agentState === "connecting"
              ? "Agent did not join the room. "
              : "Agent connected but did not complete initializing. ";

          toast.error(`Session ended: ${reason}`);
          if (room) {
            room.disconnect();
          }
        }
      }, 10_000);

      return () => clearTimeout(timeout);
    }
  }, [agentState, sessionStarted, room]);

  return (
    <main
      ref={ref}
      inert={disabled}
      className={cn("relative flex h-full w-full flex-col overflow-hidden")}
    >
      <div className="flex min-h-0 flex-1 flex-col pb-20">
        <div
          className={cn(
            "flex flex-shrink-0 items-center justify-center overflow-hidden px-4",
            chatOpen ? "h-16" : "flex-1",
          )}
        >
          <MediaTiles chatOpen={chatOpen} />
        </div>

        {chatOpen && (
          <div className="mt-4 flex max-h-[65vh] min-h-0 flex-1 flex-col">
            <div
              className={cn(
                "scrollbar-hide flex-1 overflow-y-auto px-4",
                "scroll-smooth",
                "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
              )}
            >
              <div className="mx-auto max-w-[62rem]">
                <ChatRenderer convoMessages={messages} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="absolute right-0 bottom-0 left-0 z-10">
        <div className="flex justify-center pb-6">
          <AgentControlBar
            onChatOpenChange={setChatOpen}
            onDisconnect={handleEndCall}
          />
        </div>
      </div>
    </main>
  );
};
