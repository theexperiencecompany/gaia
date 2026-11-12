"use client";

import { Modal, Spinner } from "@heroui/react";
import { AlertCircleIcon } from "@icons";
import type React from "react";
import { modalVariants } from "@/components/shared/controlVariants";
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
        <Spinner size="md" />
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
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog
            className={modalVariants({
              size: "3xl",
              className: "bg-zinc-900 border border-zinc-800",
            })}
          >
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="border-b border-zinc-800 pb-3">
              <Modal.Heading className="text-sm font-medium text-zinc-200">
                {title}
              </Modal.Heading>
            </Modal.Header>
            <Modal.Body className="py-4">
              {renderBody({ isLoading, hasError, errorMessage, content })}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
};

export default MarkdownViewerModal;
