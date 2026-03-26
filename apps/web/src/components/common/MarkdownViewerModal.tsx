"use client";

import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/react";
import { Spinner } from "@heroui/spinner";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

interface MarkdownViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  content: string | null;
  isLoading?: boolean;
}

const MarkdownViewerModal: React.FC<MarkdownViewerModalProps> = ({
  isOpen,
  onClose,
  title,
  content,
  isLoading,
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
          {isLoading ? (
            <div className="flex items-center justify-center py-16">
              <Spinner size="md" color="default" />
            </div>
          ) : content ? (
            <MarkdownRenderer content={content} className="text-sm" />
          ) : (
            <p className="py-8 text-center text-sm text-zinc-500">
              No content available.
            </p>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

export default MarkdownViewerModal;
