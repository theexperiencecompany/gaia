"use client";

import { Button, Modal } from "@heroui/react";

import MemoryManagement from "@/features/memory/components/MemoryManagement";

interface MemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function MemoryModal({ isOpen, onClose }: MemoryModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      {/* z-[50]: lower z-index than child modals */}
      <Modal.Backdrop isDismissable className="z-[50]">
        <Modal.Container size="lg" className="z-[50]">
          <Modal.Dialog className="max-w-4xl">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Body className="py-6">
              <div className="font-bold">Your Memories</div>
              <MemoryManagement autoFetch={isOpen} />
            </Modal.Body>

            <Modal.Footer>
              <Button variant="ghost" onPress={onClose}>
                Close
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
