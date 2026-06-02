import type React from "react";

import { ChatSection } from "@/features/chat/components/interface/sections/ChatSection";

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
  /**
   * Bottom-bar slot. In text mode this is the `<Composer/>`; in voice mode
   * it's the voice control bar container. The layout, scroll wiring, and
   * drag-and-drop survive across mode flips.
   */
  bottomBar: React.ReactNode;
}

export const ChatWithMessages: React.FC<ChatWithMessagesProps> = ({
  scrollContainerRef,
  chatRef,
  handleScroll,
  dragHandlers,
  bottomBar,
}) => {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Scrollable chat content */}
      <div
        ref={scrollContainerRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        onScroll={handleScroll}
        {...dragHandlers}
      >
        <ChatSection chatRef={chatRef} />
      </div>
      {/* Fixed bottom slot (composer in text mode, voice bar in voice mode) */}
      <div className="shrink-0 pb-2">{bottomBar}</div>
    </div>
  );
};
