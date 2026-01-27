"use client";

import { Kbd } from "@heroui/kbd";
import {
  Button,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { useEffect, useRef } from "react";

interface ConfirmationDialogProps {
  isOpen: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
  isLoading?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmationDialog({
  isOpen,
  title = "Confirm Action",
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "default",
  isLoading = false,
  onConfirm,
  onCancel,
}: ConfirmationDialogProps) {
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  // Track if confirm was just pressed to avoid triggering onCancel
  const confirmPressedRef = useRef(false);

  useEffect(() => {
    if (!isOpen) {
      // Reset the flag when dialog closes
      confirmPressedRef.current = false;
      return;
    }

    // Focus the confirm button when dialog opens
    const timer = setTimeout(() => {
      confirmButtonRef.current?.focus();
    }, 100);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        confirmPressedRef.current = true;
        onConfirm();
      } else if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onConfirm, onCancel]);

  const handleOpenChange = (open: boolean) => {
    if (!open && !confirmPressedRef.current) {
      onCancel();
    }
  };

  const handleConfirmPress = () => {
    confirmPressedRef.current = true;
    onConfirm();
  };

  return (
    <Modal isOpen={isOpen} onOpenChange={handleOpenChange}>
      <ModalContent>
        {(onClose) => (
          <>
            <ModalHeader className="flex flex-col gap-1">{title}</ModalHeader>
            <ModalBody>
              <p>{message}</p>
            </ModalBody>
            <ModalFooter>
              <Button
                variant="flat"
                onPress={() => {
                  onCancel();
                  onClose();
                }}
                className="bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                endContent={<Kbd keys={["escape"]} />}
                isDisabled={isLoading}
              >
                {cancelText}
              </Button>
              <Button
                ref={confirmButtonRef}
                color={variant === "destructive" ? "danger" : "primary"}
                onPress={() => {
                  handleConfirmPress();
                  onClose();
                }}
                endContent={!isLoading && <Kbd keys={["enter"]} />}
                isLoading={isLoading}
                isDisabled={isLoading}
              >
                {confirmText}
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
