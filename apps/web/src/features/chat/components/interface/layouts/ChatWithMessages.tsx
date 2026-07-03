import type React from "react";

import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { ChatSection } from "@/features/chat/components/interface/sections/ChatSection";

interface ChatWithMessagesProps {
  chatRef: React.RefObject<HTMLDivElement | null>;
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
  chatRef,
  dragHandlers,
  bottomBar,
}) => {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Scrollable transcript — the message scroller owns scroll position:
          it follows the live edge while streaming and releases when the
          reader scrolls up. Must render inside MessageScrollerProvider. */}
      <MessageScroller className="min-h-0 flex-1">
        <MessageScrollerViewport {...dragHandlers}>
          <MessageScrollerContent>
            <ChatSection chatRef={chatRef} />
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
      {/* Fixed bottom slot (composer in text mode, voice bar in voice mode) */}
      <div className="shrink-0 pb-2">{bottomBar}</div>
    </div>
  );
};
