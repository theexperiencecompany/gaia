import type React from "react";

import Composer from "@/features/chat/components/composer/Composer";

import { ChatSection } from "@/features/chat/components/interface/sections/ChatSection";

interface ChatWithMessagesProps {
  scrollContainerRef: (node: HTMLElement | null) => void;
  contentRef: (node: HTMLElement | null) => void;
  chatRef: React.RefObject<HTMLDivElement | null>;
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
  contentRef,
  chatRef,
  dragHandlers,
  composerProps,
}) => {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Scrollable chat content — stick-to-bottom owns scroll position */}
      <div
        ref={scrollContainerRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        {...dragHandlers}
      >
        <div ref={contentRef}>
          <ChatSection chatRef={chatRef} />
        </div>
      </div>
      {/* Fixed composer at bottom */}
      <div className="shrink-0 pb-2">
        <Composer {...composerProps} />
      </div>
    </div>
  );
};
