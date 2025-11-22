import React from "react";

import Composer from "@/features/chat/components/composer/Composer";
import StarterText from "@/features/chat/components/interface/StarterText";

import { ChatSuggestions } from "./ChatSuggestions";

interface NewChatSectionProps {
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
  };
}

export const NewChatSection: React.FC<NewChatSectionProps> = ({
  composerProps,
}) => {
  return (
    <div className="relative flex w-full snap-start items-center justify-center p-4 pt-[28vh]">
      <div className="flex w-full max-w-7xl flex-col items-center justify-center gap-3">
        <div className="flex flex-col items-center gap-2">
          <StarterText />
        </div>
        <div className="mt-12 w-full max-w-7xl">
          <Composer {...composerProps} />
        </div>

        <ChatSuggestions />
        {/* <CardStackContainer /> */}
      </div>
    </div>
  );
};
