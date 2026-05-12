/**
 * Layout used the first time a freshly-onboarded user lands on `/c`.
 * Renders the post-onboarding welcome experience above the composer.
 * Mirrors `ChatWithMessages` so scrolling + composer behavior matches the
 * real chat surface.
 */

import type React from "react";
import Composer from "@/features/chat/components/composer/Composer";
import { WelcomeChat } from "@/features/chat/components/welcome/WelcomeChat";

interface WelcomeChatLayoutProps {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
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
    appendToInputRef: React.RefObject<((text: string) => void) | null>;
    droppedFiles: File[];
    onDroppedFilesProcessed: () => void;
    hasMessages: boolean;
    conversationId?: string;
    voiceModeActive: () => void;
  };
}

export const WelcomeChatLayout: React.FC<WelcomeChatLayoutProps> = ({
  scrollContainerRef,
  handleScroll,
  dragHandlers,
  composerProps,
}) => {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scrollContainerRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4"
        onScroll={handleScroll}
        {...dragHandlers}
      >
        <WelcomeChat />
      </div>
      <div className="shrink-0 pb-2">
        <Composer {...composerProps} />
      </div>
    </div>
  );
};
