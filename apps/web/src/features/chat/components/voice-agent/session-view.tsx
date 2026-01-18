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
import { db, type IConversation } from "@/lib/db/chatDb";
import { cn } from "@/lib/utils";

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
  const [conversationDescription, setConversationDescription] = useState<
    string | null
  >(null);
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
          } catch (err) {
            console.error("Failed to read text stream:", err);
          }
        };
        handleStream();
      }
    };

    const conversationDescriptionHandler = (reader: TextStreamReader) => {
      if (reader.info.topic === "conversation-description") {
        const handleStream = async () => {
          try {
            const text = await reader.readAll();
            setConversationDescription(text);
          } catch (err) {
            console.error("Failed to read conversation description:", err);
          }
        };
        handleStream();
      }
    };

    const registerHandler = () => {
      try {
        room.unregisterTextStreamHandler("conversation-id");
        room.unregisterTextStreamHandler("conversation-description");
      } catch {
        // Ignore error if no handler was registered
      }

      room.registerTextStreamHandler("conversation-id", conversationIdHandler);
      room.registerTextStreamHandler(
        "conversation-description",
        conversationDescriptionHandler,
      );
    };

    room.on("connected", registerHandler);

    if (room.state === "connected") {
      registerHandler();
    }

    return () => {
      room.off("connected", registerHandler);
      try {
        room.unregisterTextStreamHandler("conversation-id");
        room.unregisterTextStreamHandler("conversation-description");
      } catch {
        // Ignore error if no handler was registered
      }
    };
  }, [room]);

  // Create conversation in sidebar when we have both ID and description
  useEffect(() => {
    if (!conversationId || !conversationDescription) {
      return;
    }

    const createConversationInSidebar = async () => {
      try {
        // Check if conversation already exists
        const existingConversation = await db.getConversation(conversationId);

        if (existingConversation) {
          // Update description if it changed
          if (existingConversation.description !== conversationDescription) {
            const updatedConversation: IConversation = {
              ...existingConversation,
              title: conversationDescription,
              description: conversationDescription,
              updatedAt: new Date(),
            };
            await db.putConversation(updatedConversation);
          }
        } else {
          // Create new conversation
          const newConversation: IConversation = {
            id: conversationId,
            title: conversationDescription,
            description: conversationDescription,
            starred: false,
            isSystemGenerated: false,
            systemPurpose: null,
            isUnread: false,
            createdAt: new Date(),
            updatedAt: new Date(),
          };
          await db.putConversation(newConversation);
        }
      } catch (error) {
        console.error("Failed to create conversation in sidebar:", error);
      }
    };

    createConversationInSidebar();
  }, [conversationId, conversationDescription]);

  const handleEndCall = React.useCallback(async () => {
    // Navigate to the conversation page and trigger sync to fetch messages from backend
    // This avoids duplicate saves to IndexedDB
    if (conversationId) {
      router.push(`/c/${conversationId}?sync=true`);
    } else {
      // No conversationId found, staying on current page
    }
    onEndCall();
  }, [onEndCall, conversationId, router]);

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
