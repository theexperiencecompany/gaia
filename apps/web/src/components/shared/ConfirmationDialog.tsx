"use client";

import { Kbd, Modal } from "@heroui/react";
import { useEffect, useEffectEvent, useRef } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";

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

  const handleKeyDown = useEffectEvent((e: KeyboardEvent) => {
    if (!isOpen) return;
    if (e.key === "Enter") {
      e.preventDefault();
      confirmPressedRef.current = true;
      onConfirm();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  });

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

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

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
      <Modal.Backdrop>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">{title}</Modal.Header>
            <Modal.Body>
              <p>{message}</p>
            </Modal.Body>
            <Modal.Footer>
              <GaiaButton
                variant="tertiary"
                tone="dim"
                onPress={() => {
                  onCancel();
                  handleOpenChange(false);
                }}
                isDisabled={isLoading}
              >
                {cancelText}
                <Kbd>
                  <Kbd.Abbr keyValue="escape" />
                </Kbd>
              </GaiaButton>
              <GaiaButton
                ref={confirmButtonRef}
                onPress={handleConfirmPress}
                variant={variant === "destructive" ? "danger" : "primary"}
                isPending={isLoading}
                isDisabled={isLoading}
              >
                {confirmText}
                {!isLoading && (
                  <Kbd>
                    <Kbd.Abbr keyValue="enter" />
                  </Kbd>
                )}
              </GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
