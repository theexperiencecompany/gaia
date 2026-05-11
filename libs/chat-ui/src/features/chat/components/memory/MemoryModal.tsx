"use client";

import { Button } from "@heroui/button";
import { Modal, ModalBody, ModalContent, ModalFooter } from "@heroui/modal";

import MemoryManagement from "@/features/memory/components/MemoryManagement";

interface MemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function MemoryModal({ isOpen, onClose }: MemoryModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="4xl"
      scrollBehavior="inside"
      isDismissable={true}
      backdrop="blur"
      classNames={{
        body: "py-6",
        base: "z-[50]", // Lower z-index than child modal
        wrapper: "z-[50]", // Lower z-index than child modal
      }}
    >
      <ModalContent>
        {(onClose) => (
          <>
            <ModalBody>
              <div className="font-bold">Your Memories</div>
              <MemoryManagement onClose={onClose} autoFetch={isOpen} />
            </ModalBody>

            <ModalFooter>
              <Button color="default" variant="light" onPress={onClose}>
                Close
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
