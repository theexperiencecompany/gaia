"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { CheckmarkCircle02Icon } from "@icons";
import type React from "react";
import { StagedDeliverablePreview } from "@/features/todo/components/shared/StagedDeliverablePreview";

interface ApproveConfirmModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  todoId: string;
  fallbackPreview?: string | null;
  onConfirm: () => void;
  isConfirming: boolean;
}

/**
 * Confirmation gate before GAIA releases a staged deliverable: the exact
 * content it will send, and an explicit "Approve & send". Used from surfaces
 * (like the dashboard) where approving needs a look at the content first.
 */
export const ApproveConfirmModal: React.FC<ApproveConfirmModalProps> = ({
  isOpen,
  onOpenChange,
  todoId,
  fallbackPreview,
  onConfirm,
  isConfirming,
}) => {
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="lg"
      placement="center"
    >
      <ModalContent>
        {(onClose) => (
          <>
            <ModalHeader className="text-amber-400">
              GAIA wants to send this
            </ModalHeader>
            <ModalBody>
              <StagedDeliverablePreview
                todoId={todoId}
                fallbackPreview={fallbackPreview}
              />
            </ModalBody>
            <ModalFooter>
              <Button variant="flat" radius="lg" onPress={onClose}>
                Cancel
              </Button>
              <Button
                color="primary"
                radius="lg"
                startContent={<CheckmarkCircle02Icon className="size-4" />}
                isLoading={isConfirming}
                onPress={onConfirm}
              >
                Approve & send
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
};
