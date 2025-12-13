import { Button } from "@heroui/button";
import type React from "react";
import { useState } from "react";
import { ArrowDown02Icon, ChevronUp } from "@/components";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";
import { NewChatSection } from "../sections";

interface NewChatLayoutProps {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
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
  };
}

export const NewChatLayout: React.FC<NewChatLayoutProps> = ({
  scrollContainerRef,
  dummySectionRef,
  handleScroll,
  dragHandlers,
  composerProps,
}) => {
  const [showUseCases, setShowUseCases] = useState(false);

  return (
    <div
      ref={scrollContainerRef}
      className="h-full space-y-20 overflow-y-auto"
      onScroll={handleScroll}
      {...dragHandlers}
    >
      <div className="flex w-full flex-col items-center gap-10 px-4 pb-10">
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
          />
        )}
      </div>
    </div>
  );
};
