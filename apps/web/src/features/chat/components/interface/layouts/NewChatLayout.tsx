import { Button } from "@heroui/button";
import type React from "react";
import { useState } from "react";
import { ChevronUp } from "@/components/shared/icons";
import { NewChatSection } from "@/features/chat/components/interface/sections/NewChatSection";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";

interface NewChatLayoutProps {
  scrollContainerRef: (node: HTMLElement | null) => void;
  contentRef: (node: HTMLElement | null) => void;
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
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
    voiceModeActive: () => void;
  };
}

export const NewChatLayout: React.FC<NewChatLayoutProps> = ({
  scrollContainerRef,
  contentRef,
  dummySectionRef,
  dragHandlers,
  composerProps,
}) => {
  const [showUseCases, setShowUseCases] = useState(false);

  return (
    <div
      ref={scrollContainerRef}
      className="h-full space-y-20 overflow-y-auto"
      {...dragHandlers}
    >
      <div
        ref={contentRef}
        className="flex w-full flex-col items-center gap-10 px-4 pb-10"
      >
        <NewChatSection
          composerProps={composerProps}
          showUseCases={showUseCases}
        />

        {!showUseCases && (
          <Button
            className="font-medium text-zinc-300"
            radius="full"
            variant="flat"
            onPress={() => setShowUseCases(true)}
          >
            Explore Use Cases <ChevronUp />
          </Button>
        )}

        {showUseCases && (
          <UseCaseSection
            dummySectionRef={dummySectionRef}
            setShowUseCases={setShowUseCases}
            showDescriptionAsTooltip={true}
            hideUserWorkflows={false}
          />
        )}
      </div>
    </div>
  );
};
