"use client";

import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/react";
import { Spinner } from "@heroui/spinner";
import { AlertCircleIcon } from "@icons";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

interface MarkdownViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  content: string | null;
  isLoading?: boolean;
  hasError?: boolean;
  errorMessage?: string;
}

function renderBody({
  isLoading,
  hasError,
  errorMessage,
  content,
}: {
  isLoading?: boolean;
  hasError?: boolean;
  errorMessage: string;
  content: string | null;
}): React.ReactNode {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner size="md" color="default" />
      </div>
    );
  }
  if (hasError) {
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <AlertCircleIcon width={28} height={28} className="text-red-400" />
        <p className="text-sm text-zinc-400">{errorMessage}</p>
      </div>
    );
  }
  if (content) {
    return <MarkdownRenderer content={content} className="text-sm" />;
  }
  return (
    <p className="py-8 text-center text-sm text-zinc-500">
      No content available.
    </p>
  );
}

const MarkdownViewerModal: React.FC<MarkdownViewerModalProps> = ({
  isOpen,
  onClose,
  title,
  content,
  isLoading,
  hasError,
  errorMessage = "Something went wrong while loading this file.",
}) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="3xl"
      scrollBehavior="inside"
      classNames={{
        base: "bg-zinc-900 border border-zinc-800",
        header: "border-b border-zinc-800 pb-3",
        body: "py-4",
      }}
    >
      <ModalContent>
        <ModalHeader className="text-sm font-medium text-zinc-200">
          {title}
        </ModalHeader>
        <ModalBody>
          {renderBody({ isLoading, hasError, errorMessage, content })}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

export default MarkdownViewerModal;
