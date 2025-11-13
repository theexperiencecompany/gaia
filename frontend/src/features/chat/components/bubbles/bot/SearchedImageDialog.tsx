import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import Image from "next/image";

import { useImageDialog } from "@/stores/uiStore";

export default function SearchedImageDialog() {
  const { isOpen, selectedImage, closeDialog } = useImageDialog();

  return (
    <Modal
      className="h-full text-foreground dark"
      isOpen={isOpen}
      onOpenChange={closeDialog}
      size="5xl"
      scrollBehavior="inside"
    >
      <ModalContent>
        <ModalBody className="max-h-[80vh] overflow-auto">
          {selectedImage && (
            <Image
              src={selectedImage}
              alt="Search result image"
              fill
              className="h-full w-full rounded-lg object-contain p-10"
              priority
            />
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
