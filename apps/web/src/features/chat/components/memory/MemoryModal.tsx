"use client";

import { Modal } from "@heroui/react";
import { modalVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
        <Modal.Container className="z-[50]">
          <Modal.Dialog
            className={modalVariants({ size: "4xl", className: "max-w-4xl" })}
          >
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Body>
              <div className="flex flex-col gap-3 py-4">
                <div className="font-bold">Your Memories</div>
                <MemoryManagement autoFetch={isOpen} />
              </div>
            </Modal.Body>

            <Modal.Footer>
              <GaiaButton variant="ghost" onPress={onClose}>
                Close
              </GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
