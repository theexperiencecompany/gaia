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
      className="text-foreground dark"
      isOpen={isOpen}
      onOpenChange={closeDialog}
      size="2xl"
      scrollBehavior="inside"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Image Preview</h2>
        </ModalHeader>
        <ModalBody className="p-0">
          {selectedImage && (
            <div className="flex flex-col gap-4">
              <div className="relative w-full">
                <Image
                  src={selectedImage}
                  alt="Search result image"
                  width={800}
                  height={600}
                  className="w-full rounded-lg object-contain"
                  priority
                />
              </div>
            </div>
          )}
        </ModalBody>
        <ModalFooter className="flex justify-between">
          {selectedImage && (
            <a
              href={selectedImage}
              target="_blank"
              rel="noopener noreferrer"
              className="max-w-md truncate text-sm text-foreground-500 transition hover:text-primary"
            >
              {selectedImage}
            </a>
          )}
          <Button color="primary" onPress={closeDialog}>
            Close
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
