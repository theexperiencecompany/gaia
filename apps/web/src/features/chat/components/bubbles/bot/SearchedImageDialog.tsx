import { Modal } from "@heroui/react";
import Image from "next/image";

import { useImageDialog } from "@/stores/uiStore";

export default function SearchedImageDialog() {
  const { isOpen, selectedImage, closeDialog } = useImageDialog();

  return (
    <Modal isOpen={isOpen} onOpenChange={closeDialog}>
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog className="h-full max-w-5xl text-foreground dark">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Body className="max-h-[80vh] overflow-auto">
              {selectedImage && (
                <Image
                  src={selectedImage}
                  alt="Search result image"
                  fill
                  sizes="(max-width: 1024px) 100vw, 944px"
                  className="h-full w-full rounded-lg object-contain p-10"
                  priority
                />
              )}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
