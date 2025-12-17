import type React from "react";

import Composer from "@/features/chat/components/composer/Composer";

import { ChatSection } from "../sections";

interface ChatWithMessagesProps {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  chatRef: React.RefObject<HTMLDivElement | null>;
  handleScroll: (event: React.UIEvent) => void;
  dragHandlers: {
    onDragEnter: (e: React.DragEvent<HTMLElement>) => void;
    onDragOver: (e: React.DragEvent<HTMLElement>) => void;
    onDragLeave: (e: React.DragEvent<HTMLElement>) => void;
    onDrop: (e: React.DragEvent<HTMLElement>) => void;
  };
  composerProps: {
    inputRef: React.RefObject<HTMLTextAreaElement | null>;
    scrollToBottom: () => void;
    fileUploadRef: React.RefObject<{
      openFileUploadModal: () => void;
      handleDroppedFiles: (files: File[]) => void;
    } | null>;
    droppedFiles: File[];
    onDroppedFilesProcessed: () => void;
    hasMessages: boolean;
    conversationId?: string;
    voiceModeActive: () => void;
  };
}

export const ChatWithMessages: React.FC<ChatWithMessagesProps> = ({
  scrollContainerRef,
  chatRef,
  handleScroll,
  dragHandlers,
  composerProps,
}) => {
  return (
    <div className="flex h-full flex-col">
      {/* Scrollable chat content */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto"
        onScroll={handleScroll}
        {...dragHandlers}
      >
        <ChatSection chatRef={chatRef} />
      </div>
      {/* Fixed composer at bottom */}
      <div className="shrink-0 pb-2">
        <Composer {...composerProps} />
      </div>
    </div>
  );
};
